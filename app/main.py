import mimetypes
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import documents, learner_types, library, versions
from .ai import AIContext, get_provider
from .ai.base import InputError
from .config import LIBRARY_CATEGORIES, REGULATIONS_DIR, STATIC_DIR
from .extract import extract_text
from .personas import build_personas
from .regulations import RegulationStore
from .schemas import (
    AnalyzeReq, ApplyFeedbackReq, Curriculum, DocContext, DocPart, FilledForm, FillFormsReq, GenerateReq, MaterialsReq, ParseReq,
    ReviseReq, SaveReq, Survey, Validation, ValidateReq,
)

# 한글 파일을 내려받을 때 형식을 바르게 알려 준다
mimetypes.add_type("application/hwp+zip", ".hwpx")

app = FastAPI(title="커리큘럼 에이전트 프로토타입")
regulations = RegulationStore(REGULATIONS_DIR)
library.migrate_legacy()


def _ctx(context: DocContext, survey: Survey) -> AIContext:
    return AIContext(context.application_docs, context.criteria, survey, regulations.search(survey), context.documents)


def _call(fn, *args):
    try:
        return fn(*args)
    except InputError as e:
        raise HTTPException(400, str(e))
    except NotImplementedError as e:
        raise HTTPException(501, str(e))
    except Exception as e:  # AI 호출 실패를 화면에 그대로 보여준다
        raise HTTPException(502, f"AI 호출 실패: {e}")


def _curriculum(data) -> dict:
    return Curriculum.model_validate(data).model_dump()


def _regs(ctx: AIContext) -> List[dict]:
    return [r.model_dump() for r in ctx.regulations]


@app.get("/api/status")
def status():
    return {"provider": get_provider().name, "regulations": regulations.status(), "categories": LIBRARY_CATEGORIES}


@app.post("/api/extract")
async def extract(file: UploadFile = File(...)):
    try:
        return {"text": extract_text(file.filename or "", await file.read())}
    except Exception as e:
        raise HTTPException(400, f"텍스트 추출 실패: {e}")


@app.post("/api/analyze")
def analyze(req: AnalyzeReq):
    """신청 서류 묶음을 공고·심사기준·작성할 서류 등으로 나눈다."""
    if not req.text.strip():
        return {"documents": []}
    try:
        result = get_provider().analyze_documents(documents.outline(req.text), req.text)
    except Exception:  # AI 분석이 실패해도 규칙 기반 분할로 진행한다
        result = {}
    parts = documents.split(req.text, result.get("parts") or []) or documents.split(req.text, documents.heuristic_parts(req.text))
    return {"documents": [d.model_dump() for d in parts]}


@app.post("/api/parse")
def parse(req: ParseReq):
    if not req.text.strip():
        raise HTTPException(400, "커리큘럼 내용이 비어 있습니다.")
    return {"curriculum": _curriculum(_call(get_provider().parse, req.text))}


def _versioned(data, note: str, base: dict = None) -> dict:
    """새 버전(v1, v2 …)으로 기록한다. base가 버전 없는 예전 자료면 base를 v1로 먼저 남긴다."""
    cur = versions.record(_curriculum(data), note, base)
    out = {"curriculum": cur}
    if base is not None:
        out["base"] = {"lineage_id": base["lineage_id"], "version": base["version"]}
    return out


@app.post("/api/generate")
def generate(req: GenerateReq):
    ctx = _ctx(req.context, req.survey)
    data = _call(get_provider().generate, ctx)
    return {**_versioned(data, "생성"), "regulations": _regs(ctx)}


@app.post("/api/revise")
def revise(req: ReviseReq):
    ctx = _ctx(req.context, req.survey)
    base = req.curriculum.model_dump()
    data = _call(get_provider().revise, ctx, base, req.instruction)
    return {**_versioned(data, f"수정: {req.instruction.strip()[:40]}", req.curriculum.model_dump()), "regulations": _regs(ctx)}


@app.post("/api/validate")
def validate(req: ValidateReq):
    ctx = _ctx(req.context, req.survey)
    provider = get_provider()
    # 학생 검증 agent는 학습자 유형 카드(기본 4명 + 운영자가 추가한 유형)를, 다른 공급자는 설문으로 정한 페르소나를 쓴다
    personas = learner_types.selected(req.learner_ids) if provider.uses_learner_cards else build_personas(req.survey)
    validation = Validation.model_validate(_call(provider.validate, ctx, req.curriculum.model_dump(), personas))
    for pi, review in enumerate(validation.personas):
        for gi, gap in enumerate(review.gaps):
            gap.id, gap.persona = f"p{pi}g{gi}", review.persona
    c = req.curriculum
    if c.lineage_id and c.version:
        versions.attach(c.lineage_id, c.version, validation={
            "verdict": validation.verdict, "score": validation.score, "overall": validation.overall,
            "at": datetime.now().isoformat(timespec="seconds")})
    return {"validation": validation.model_dump(), "regulations": _regs(ctx)}


@app.post("/api/apply-feedback")
def apply_feedback(req: ApplyFeedbackReq):
    if not req.gaps:
        raise HTTPException(400, "반영할 보완점을 하나 이상 선택하세요.")
    ctx = _ctx(req.context, req.survey)
    data = _call(get_provider().apply_feedback, ctx, req.curriculum.model_dump(), [g.model_dump() for g in req.gaps])
    return {**_versioned(data, f"검증 반영: 보완점 {len(req.gaps)}개", req.curriculum.model_dump()), "regulations": _regs(ctx)}


@app.post("/api/materials")
def materials(req: MaterialsReq):
    """교과목별 학습 자료(설명 → 실습)를 만들어 지금 버전에 붙인다 (퀴즈는 생성 단계에서 이미 있음)."""
    import os

    from generator_agent.materials import build

    from .ai.agent_bridge import to_agent_curriculum

    cur = req.curriculum.model_dump()
    agent_cur = to_agent_curriculum(cur)
    if not agent_cur.get("quizzes") and cur.get("quizzes"):
        agent_cur = {**agent_cur, "quizzes": cur["quizzes"]}
    provider = "openai" if os.getenv("OPENAI_API_KEY") else "mock"
    try:
        out = build(agent_cur, target=req.survey.target_desc or req.survey.target, provider=provider)
    except Exception as e:
        raise HTTPException(502, f"학습 자료 생성 실패: {e}")
    cur["learning_materials"], cur["materials_meta"] = out["materials"], out["meta"]
    if cur.get("lineage_id") and cur.get("version"):
        versions.attach(cur["lineage_id"], cur["version"], curriculum=cur)
    return {"curriculum": _curriculum(cur)}


@app.get("/api/learner-types")
def learner_types_list():
    return {"types": learner_types.all_types()}


@app.post("/api/learner-types")
def learner_types_add(form: dict):
    try:
        return {"type": learner_types.add(form)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/learner-types/{type_id}")
def learner_types_delete(type_id: str):
    try:
        learner_types.remove(type_id)
    except FileNotFoundError:
        raise HTTPException(404, "기본 학생은 지울 수 없어요. 추가한 유형만 지울 수 있어요.")
    return {"ok": True}


@app.get("/api/versions/{lineage}")
def versions_list(lineage: str):
    try:
        return {"versions": versions.list_versions(lineage)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/versions/{lineage}/{version}")
def versions_get(lineage: str, version: int):
    try:
        return {"curriculum": _curriculum(versions.get_version(lineage, version))}
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "버전을 찾을 수 없습니다.")


def _fill_forms(context: DocContext, survey: Survey, curriculum: Curriculum, forms: List[DocPart]) -> List[FilledForm]:
    if not forms:
        return []
    ctx = _ctx(context, survey)
    data = curriculum.model_dump()
    provider = get_provider()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda f: _call(provider.fill_form, ctx, data, f.model_dump()), forms))
    return [FilledForm.model_validate(r) for r in results]


@app.post("/api/forms/fill")
def forms_fill(req: FillFormsReq):
    """미리보기용: 지정한 서식을 지금 커리큘럼으로 작성한다."""
    forms = [d for d in req.context.documents if d.kind == "form" and d.id in req.ids]
    if not forms:
        raise HTTPException(400, "작성할 서류를 찾을 수 없습니다.")
    filled = _fill_forms(req.context, req.survey, req.curriculum, forms)
    return {"forms": [{"id": d.id, "name": d.name, "form": f.model_dump()} for d, f in zip(forms, filled)]}


@app.get("/api/library")
def library_list():
    return library.list_library()


@app.post("/api/library/save")
def library_save(req: SaveReq):
    forms = [d for d in req.context.documents if d.kind == "form" and d.selected]
    done = {f.id: f.form for f in req.filled_forms}
    todo = [d for d in forms if d.id not in done]
    done.update({d.id: f for d, f in zip(todo, _fill_forms(req.context, req.survey, req.curriculum, todo))})
    filled = [(d, done[d.id]) for d in forms]
    try:
        return library.save_bundle(req, filled)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/library/{category}/{folder}")
def library_get(category: str, folder: str):
    try:
        return library.get_entry(category, folder)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "자료를 찾을 수 없습니다.")


@app.delete("/api/library/{category}/{folder}")
def library_delete(category: str, folder: str):
    try:
        library.delete_entry(category, folder)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "자료를 찾을 수 없습니다.")
    return {"ok": True}


@app.get("/api/library/{category}/{folder}/files/{filename}")
def library_file(category: str, folder: str, filename: str):
    try:
        return FileResponse(library.file_path(category, folder, filename), filename=filename)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "파일을 찾을 수 없습니다.")


@app.get("/")
def index():
    # 파일이 바뀌면 주소(?v=)도 바뀌게 해서 브라우저가 예전 app.js/style.css를 쓰지 않게 한다
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for name in ("app.js", "style.css"):
        version = int((STATIC_DIR / name).stat().st_mtime)
        html = html.replace(f"/static/{name}", f"/static/{name}?v={version}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.middleware("http")
async def no_cache_static(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

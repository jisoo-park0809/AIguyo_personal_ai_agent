"""나의 자료실: data/library/<카테고리>/<날짜_과정명>/ 폴더에 묶음으로 저장."""
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from . import exporters
from .hwpx_writer import build_form_hwpx
from .config import LEGACY_CATEGORIES, LIBRARY_CATEGORIES, LIBRARY_DIR
from .schemas import Curriculum, DocPart, FilledForm, SaveReq

META = "meta.json"
HIDDEN = {META, "curriculum.json", "context.json", "validation.json", "forms.json"}


def migrate_legacy() -> None:
    """예전 폴더 이름(1차 생성안 등)으로 저장된 자료를 새 이름 폴더로 옮긴다."""
    for old, new in LEGACY_CATEGORIES.items():
        src = LIBRARY_DIR / old
        if not src.is_dir():
            continue
        dst = LIBRARY_DIR / new
        dst.mkdir(parents=True, exist_ok=True)
        for entry in src.iterdir():
            target = dst / entry.name
            if target.exists():
                continue
            shutil.move(str(entry), str(target))
            meta = target / META
            if meta.exists():
                data = json.loads(meta.read_text(encoding="utf-8"))
                data["category"] = new
                meta.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        if not any(src.iterdir()):
            src.rmdir()


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("_")[:40] or "커리큘럼"


def _resolve(category: str, folder: str = "", filename: str = "") -> Path:
    if category not in LIBRARY_CATEGORIES:
        raise ValueError("알 수 없는 자료실 폴더입니다.")
    path = (LIBRARY_DIR / category / folder / filename).resolve()
    if LIBRARY_DIR.resolve() not in path.parents and path != LIBRARY_DIR.resolve():
        raise ValueError("잘못된 경로입니다.")
    return path


def save_bundle(req: SaveReq, forms: List[Tuple[DocPart, FilledForm]]) -> Dict:
    """forms: (원본 서식, 작성본) 목록. 비어 있으면 기본 사업계획서를 만든다."""
    c = req.curriculum
    base = f"{datetime.now():%Y%m%d_%H%M%S}_{_safe(c.title)}"
    folder, n = base, 2
    while _resolve(req.category, folder).exists():
        folder, n = f"{base}_{n}", n + 1
    out = _resolve(req.category, folder)
    out.mkdir(parents=True)

    title = _safe(c.title)
    exporters.build_pptx(c, out / f"{title}_커리큘럼.pptx")
    exporters.build_pdf(c, out / f"{title}_커리큘럼.pdf")
    if forms:
        used = set()
        for part, filled in forms:
            name = _safe(part.name)
            while name in used:
                name += "_2"
            used.add(name)
            # 원본 서식과 같은 형식으로 저장한다 (한글 → .hwpx, Word·PDF·텍스트 → .docx)
            if part.output_format == "hwpx":
                build_form_hwpx(filled, out / f"{title}_{name}.hwpx")
            else:
                exporters.build_form_docx(filled, out / f"{title}_{name}.docx")
        # 자료실 미리보기용으로 작성 내용도 남긴다
        saved_forms = [{"name": part.name, "form": filled.model_dump()} for part, filled in forms]
        (out / "forms.json").write_text(json.dumps(saved_forms, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        exporters.build_business_plan_docx(c, req.context.application_docs, req.regulations, out / f"{title}_사업계획서.docx")
    if c.learning_materials:
        exporters.build_materials_docx(c, out / f"{title}_학습자료.docx")
    if req.validation:
        exporters.build_validation_docx(req.validation, c, out / f"{title}_검증결과.docx")
        (out / "validation.json").write_text(req.validation.model_dump_json(indent=1), encoding="utf-8")

    (out / "curriculum.json").write_text(c.model_dump_json(indent=1), encoding="utf-8")
    (out / "context.json").write_text(req.context.model_dump_json(indent=1), encoding="utf-8")
    meta = {
        "category": req.category,
        "folder": folder,
        "title": c.title,
        "lineage_id": c.lineage_id,
        "version": c.version,
        "version_note": c.version_note,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "survey": req.survey.model_dump(),
    }
    (out / META).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return _entry(out)


def _entry(folder: Path) -> Dict:
    meta = json.loads((folder / META).read_text(encoding="utf-8"))
    meta["files"] = sorted(p.name for p in folder.iterdir() if p.is_file() and p.name not in HIDDEN)
    return meta


def list_library() -> Dict[str, List[Dict]]:
    result: Dict[str, List[Dict]] = {}
    for cat in LIBRARY_CATEGORIES:
        folders = [p for p in _resolve(cat).iterdir() if (p / META).exists()]
        result[cat] = [_entry(p) for p in sorted(folders, key=lambda p: p.name, reverse=True)]
    return result


def get_entry(category: str, folder: str) -> Dict:
    path = _resolve(category, folder)
    entry = _entry(path)
    entry["curriculum"] = Curriculum.model_validate_json((path / "curriculum.json").read_text(encoding="utf-8")).model_dump()
    for key, filename, empty in (("context", "context.json", {}), ("validation", "validation.json", None), ("forms", "forms.json", [])):
        f = path / filename
        entry[key] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else empty
    if not entry["forms"]:
        # forms.json이 없는 자료(예전 저장본, 기본 사업계획서)는 저장된 Word 파일을 읽어서 보여준다
        prefix = f"{_safe(entry.get('title', ''))}_"
        # 원본 서류 묶음에 있던 순서대로 탭을 보여준다
        order = [f"{prefix}{_safe(d.get('name', ''))}" for d in entry["context"].get("documents", []) if d.get("kind") == "form"]
        rank = lambda p: order.index(p.stem) if p.stem in order else len(order)
        for docx in sorted(path.glob("*.docx"), key=lambda p: (rank(p), p.name)):
            if docx.stem.endswith(("검증결과", "학습자료")):
                continue
            name = docx.stem[len(prefix):] if docx.stem.startswith(prefix) else docx.stem
            entry["forms"].append({"name": name.replace("_", " "), "form": exporters.read_form_docx(docx).model_dump()})
    return entry


def delete_entry(category: str, folder: str) -> None:
    path = _resolve(category, folder)
    if not folder or not (path / META).exists():
        raise FileNotFoundError(folder)
    shutil.rmtree(path)


def file_path(category: str, folder: str, filename: str) -> Path:
    path = _resolve(category, folder, filename)
    if not path.is_file() or filename in HIDDEN:
        raise FileNotFoundError(filename)
    return path

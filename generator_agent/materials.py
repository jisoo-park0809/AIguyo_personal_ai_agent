"""교과목별 학습 자료 (c9a): 설명 → 실습 → 퀴즈.

퀴즈는 생성 agent가 이미 썼으니, 여기서는 교과목마다 설명과 실습 자료를 쓴다.
교과목마다 AI를 한 번씩 (동시에) 부르고, 코드가 확인한다:
- 교과목 주요 내용(topics)이 자료에 모두 나오는지
- 퀴즈 정답이 자료 설명에 나오는지 (자료만 보고 퀴즈를 풀 수 있는지)
프로젝트 교과목은 설명 자료 대신 프로젝트 안내로 대신하므로 건너뛴다.
"""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional

from .pricing import cost_krw

SYSTEM = """당신은 직업훈련 과정의 교과목 학습 자료를 쓰는 강사입니다. 주어진 교과목 정보만으로 학습자가 혼자 읽고 따라 할 수 있는 자료를 씁니다.
- 순서: 개요 → 개념 설명(주요 내용마다 한 절) → 실습 → 핵심 정리.
- 개념 설명은 훈련 대상 수준에 맞춰 쉬운 말로 쓰고, 절마다 짧은 예시(코드나 상황)를 둡니다.
- 실습은 단계별로, 결과를 확인할 수 있게 씁니다. 교과목 시간 안에 할 수 있는 분량으로 정합니다.
- 함께 주는 퀴즈를 자료만 읽고 풀 수 있도록, 퀴즈가 묻는 개념을 설명에 꼭 포함합니다.
- 확실하지 않은 사실(도구 버전, 수치, 기관·기업 정보)은 지어내지 말고 "[작성 필요: 무엇]"으로 남깁니다."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["overview", "sections", "practices", "summary_points"],
    "properties": {
        "overview": {"type": "string", "description": "이 교과목에서 무엇을 왜 배우는지 2~3문장"},
        "sections": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["title", "explanation", "example"],
            "properties": {"title": {"type": "string"}, "explanation": {"type": "string"}, "example": {"type": "string"}}}},
        "practices": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["title", "goal", "steps", "expected_result", "hints"],
            "properties": {"title": {"type": "string"}, "goal": {"type": "string"},
                           "steps": {"type": "array", "items": {"type": "string"}},
                           "expected_result": {"type": "string"},
                           "hints": {"type": "array", "items": {"type": "string"}}}}},
        "summary_points": {"type": "array", "items": {"type": "string"}},
    },
}


def _norm(text: str) -> str:
    return "".join(str(text).lower().split())


def _words(text: str) -> List[str]:
    return [w for w in re.split(r"[\s·,()/\-]+", str(text).lower()) if len(w) >= 2]


def _covered(term: str, body: str) -> bool:
    """통째로 나오거나, 2글자 이상 단어의 절반 이상이 나오면 다룬 것으로 본다."""
    if _norm(term) in body:
        return True
    ws = _words(term)
    return bool(ws) and sum(_norm(w) in body for w in ws) * 2 >= len(ws)


def check(material: Dict, subject: Dict, quizzes: List[Dict]) -> Dict:
    explain = _norm(" ".join([material.get("overview", "")]
                             + [s["title"] + s["explanation"] + s["example"] for s in material.get("sections", [])]
                             + material.get("summary_points", [])))
    everything = explain + _norm(json.dumps(material.get("practices", []), ensure_ascii=False))
    missing_topics = [t for t in subject.get("topics", []) if not _covered(t, everything)]
    unanswerable = []
    for q in quizzes:
        for i, qq in enumerate(q.get("questions", []), 1):
            answer = qq["choices"][qq["answer"] - 1]
            if not _covered(answer, explain):
                unanswerable.append(f"{i}번 (정답: {answer})")
    todo = len(re.findall(r"\[작성 필요", json.dumps(material, ensure_ascii=False)))
    return {"missing_topics": missing_topics, "quiz_answers_not_explained": unanswerable, "placeholders": todo,
            "ok": not missing_topics and not unanswerable}


def _prompt(subject: Dict, quizzes: List[Dict], target: str, field: str) -> str:
    qs = [{"question": qq["question"], "answer": qq["choices"][qq["answer"] - 1]}
          for q in quizzes for qq in q.get("questions", [])]
    info = {"분야": field, "훈련 대상": target, "교과목": subject["title"],
            "시간": {"이론": subject.get("theory_hours", 0), "실습": subject.get("practice_hours", 0)},
            "학습목표": subject.get("goals", []), "주요 내용": subject.get("topics", []),
            "선수 지식": subject.get("prerequisites", []), "평가": subject.get("assessment", ""),
            "이 교과목 퀴즈(문제와 정답)": qs}
    return "아래 교과목의 학습 자료를 쓰세요.\n" + json.dumps(info, ensure_ascii=False, indent=1)


def _mock(subject: Dict, quizzes: List[Dict]) -> Dict:
    answers = [qq["choices"][qq["answer"] - 1] for q in quizzes for qq in q.get("questions", [])]
    return {
        "overview": f"{subject['title']}에서는 {', '.join(subject.get('topics', [])[:3])} 등을 배웁니다. (시연용 자료)",
        "sections": [{"title": t, "explanation": f"{t}의 개념을 설명합니다. [작성 필요: 상세 설명]", "example": "[작성 필요: 예시]"}
                     for t in subject.get("topics", [])]
                    + ([{"title": "퀴즈 핵심 개념", "explanation": " / ".join(answers), "example": ""}] if answers else []),
        "practices": [{"title": f"{subject['title']} 실습", "goal": "배운 내용을 직접 해 본다",
                       "steps": ["예제를 따라 만든다", "조건을 바꿔 다시 실행한다"], "expected_result": "실행 결과를 확인한다",
                       "hints": ["막히면 개념 설명의 예시를 다시 본다"]}],
        "summary_points": subject.get("topics", [])[:3],
    }


def build(cur: Dict, target: str = "", provider: str = "openai", subject_ids: Optional[List[str]] = None,
          on_event: Callable[[str], None] = lambda m: None) -> Dict:
    """생성 agent 형식 커리큘럼(cur)의 교과목별 학습 자료를 만든다. 돌려주는 값: {"materials": [...], "meta": {...}}"""
    started = time.time()
    model = os.getenv("MATERIALS_MODEL") or os.getenv("GENERATOR_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
    quizzes = {}
    for q in cur.get("quizzes", []):
        quizzes.setdefault(q["subject_id"], []).append(q)
    subjects = [s for s in cur.get("subjects", []) if s.get("category") != "프로젝트"
                and (not subject_ids or s["id"] in subject_ids)]
    field = cur.get("meta", {}).get("field", "")
    cost = [0.0]
    client = None
    if provider != "mock":
        from openai import OpenAI

        client = OpenAI(timeout=float(os.getenv("OPENAI_TIMEOUT", "120")), max_retries=2)
        try:
            from langsmith.wrappers import wrap_openai
            client = wrap_openai(client)
        except ImportError:
            pass

    def one(s: Dict) -> Dict:
        qs = quizzes.get(s["id"], [])
        error = ""
        if client is None:
            body = _mock(s, qs)
        else:
            body = None
            for _ in range(2):  # 한 번 실패하면 다시 시도한다
                try:
                    resp = client.chat.completions.create(
                        model=model,
                        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": _prompt(s, qs, target, field)}],
                        response_format={"type": "json_schema", "json_schema": {"name": "learning_material", "strict": True, "schema": SCHEMA}})
                    if resp.usage:
                        details = getattr(resp.usage, "prompt_tokens_details", None)
                        cached = (getattr(details, "cached_tokens", 0) or 0) if details else 0
                        cost[0] += cost_krw(model, resp.usage.prompt_tokens, resp.usage.completion_tokens, cached)
                    body = json.loads(resp.choices[0].message.content or "{}")
                    break
                except Exception as e:
                    error = f"{type(e).__name__}: {e}"[:200]
            if body is None:
                body = {"overview": f"[작성 필요: 자료 생성 실패 — {error}]", "sections": [], "practices": [], "summary_points": []}
        on_event(f"{s['id']} {s['title']} 자료 완료")
        return {"subject_id": s["id"], "title": s["title"], **body, "checks": check(body, s, qs)}

    with ThreadPoolExecutor(max_workers=min(6, max(len(subjects), 1))) as ex:
        materials = list(ex.map(one, subjects))
    meta = {"provider": provider, "model": model if provider != "mock" else "", "subjects": len(materials),
            "seconds": round(time.time() - started, 1), "cost_krw": round(cost[0], 1),
            "checks_ok": sum(m["checks"]["ok"] for m in materials)}
    return {"materials": materials, "meta": meta}

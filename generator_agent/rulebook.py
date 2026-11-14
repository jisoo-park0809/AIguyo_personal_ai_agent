"""운영 규정 조항 목록(data/regulation_rules.json)을 읽고, 계산·구조 조항을 코드로 대조한다.

판단 조항은 여기서 판정하지 않는다(별도 심사 AI: regulation_judge.py). 대조표에는 '판정 전'으로 들어간다.
"""
import json
from functools import lru_cache
from typing import Callable, Dict, List, Optional, Tuple

from .profiles import DATA

QUIZ_MIN_QUESTIONS = 3  # 프로젝트가 아닌 교과목마다 필요한 퀴즈 문항 수
ASSESSMENT_GAP_WEEKS = 4  # 평가 사이 간격이 이보다 길면 경고 (규정에 숫자가 없어 팀이 정한 기본값)

OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, "==": lambda a, b: abs(a - b) < 1e-6}
OP_TEXT = {">=": "이상", "<=": "이하", "==": "같음"}


@lru_cache(maxsize=None)
def _book() -> Dict:
    return json.loads((DATA / "regulation_rules.json").read_text(encoding="utf-8"))


def load_rules(profile: str, training_mode: str) -> List[Dict]:
    """사업 프로필과 훈련 방식에 해당하는 조항만 고른다."""
    book = _book()
    rules = []
    for r in book["rules"]:
        if profile not in r.get("applies_to", []):
            continue
        if r.get("modes") and training_mode not in r["modes"]:
            continue
        rules.append({**r, "source_name": book["sources"].get(r["source"], r["source"])})
    return rules


def brief(rule: Dict) -> Dict:
    """AI에게 보여주는 조항 요약."""
    keys = ("id", "article", "text", "type", "metric", "op", "value", "check", "exception", "confirmed")
    return {k: rule[k] for k in keys if k in rule}


# ---------- 구조 조항: 항목이 있는지·연결됐는지 ----------

def _skill_targets(ws, rule) -> Tuple[Optional[bool], str]:
    ts = ws.cur.skill_targets
    if not ts:
        return False, "숙련목표 없음"
    unlinked = [t.id for t in ts if not t.subject_ids]
    if unlinked:
        return False, f"교과목이 연결되지 않은 숙련목표 {unlinked}"
    return True, f"숙련목표 {len(ts)}개 ({', '.join(t.id for t in ts)})"


def assessment_weeks(ws) -> List[int]:
    """평가가 있는 주차: 퀴즈 주차 + 프로젝트 교과목이 끝나는 주차(성과물 평가)."""
    weeks = {ws.quiz_week(q) for q in ws.cur.quizzes}
    sched = {w["id"]: w for w in ws.schedule()["weeks"]}
    weeks |= {sched[s.id]["week_end"] for s in ws.cur.subjects if s.category == "프로젝트" and s.id in sched}
    return sorted(w for w in weeks if w)


def max_gap(ws) -> Tuple[int, str]:
    """평가 없이 지나가는 가장 긴 기간(주). 과정 시작부터 첫 평가까지도 포함한다."""
    weeks = assessment_weeks(ws)
    total = ws.schedule()["total_weeks"]
    if not weeks:
        return total, "평가 없음"
    points = [0] + weeks
    gap, where = 0, ""
    for a, b in zip(points, points[1:]):
        if b - a > gap:
            gap, where = b - a, f"{a + 1}~{b}주차"
    return gap, where


def _periodic_assessment(ws, rule) -> Tuple[Optional[bool], str]:
    missing = [s.id for s in ws.cur.subjects if s.category != "프로젝트"
               and sum(len(q.questions) for q in ws.cur.quizzes if q.subject_id == s.id) < QUIZ_MIN_QUESTIONS]
    if missing:
        return False, f"퀴즈({QUIZ_MIN_QUESTIONS}문항 이상)가 없는 교과목 {missing}"
    targets = {t.id for t in ws.cur.skill_targets}
    assessed = {x for q in ws.cur.quizzes for qq in q.questions for x in qq.skill_target_ids}
    weeks = assessment_weeks(ws)
    gap, where = max_gap(ws)
    limit = rule.get("max_gap_weeks")
    if limit and gap > limit:
        return False, f"평가 간격 최대 {gap}주 ({where}) > 기준 {limit}주"
    note = f"평가 주차 {weeks} · 최대 간격 {gap}주"
    if targets - assessed:
        note += f" · 퀴즈로 확인하지 않는 숙련목표 {sorted(targets - assessed)}"
    return True, note


def _proficiency_methods(ws, rule) -> Tuple[Optional[bool], str]:
    ms = ws.cur.proficiency_methods
    if not ms:
        return False, "숙련도 향상 방법 없음"
    return True, " / ".join(m.method for m in ms)


def _project_outputs(ws, rule) -> Tuple[Optional[bool], str]:
    ps = ws.cur.projects
    if not ps:
        return False, "프로젝트 없음"
    empty = [p.id for p in ps if not p.portfolio_output.strip() or "작성 필요" in p.portfolio_output]
    if empty:
        return False, f"성과물이 정해지지 않은 프로젝트 {empty}"
    return True, "; ".join(f"{p.id} {p.portfolio_output}" for p in ps)


def _company_tasks_linked(ws, rule) -> Tuple[Optional[bool], str]:
    tasks = ws.inp.company_tasks
    if not tasks:
        return None, "입력한 협약기업 과제가 없어 확인할 수 없음 (협약 여부는 강사 확인)"
    linked = {p.company_task_id: p.id for p in ws.cur.projects if p.company_task_id}
    missing = [t.id for t in tasks if t.id not in linked]
    if missing:
        return False, f"프로젝트에 연결되지 않은 협약기업 과제 {missing}"
    return True, ", ".join(f"{t} → {p}" for t, p in linked.items())


STRUCTURE: Dict[str, Callable] = {
    "skill_targets": _skill_targets,
    "periodic_assessment": _periodic_assessment,
    "proficiency_methods": _proficiency_methods,
    "project_outputs": _project_outputs,
    "company_tasks_linked": _company_tasks_linked,
}


# ---------- 대조 ----------

def _row(rule: Dict, verdict: str, evidence: str, by: str) -> Dict:
    if verdict == "위반" and rule.get("exception"):
        verdict, evidence = "확인 필요", f"{evidence} — 예외 조항 해당 여부 확인: {rule['exception']}"
    return {"id": rule["id"], "key": rule.get("check") or rule.get("metric", ""), "source": rule["source_name"], "article": rule["article"], "page": rule.get("page"),
            "text": rule["text"], "type": rule["type"], "verdict": verdict, "evidence": evidence, "by": by,
            "confirmed": bool(rule.get("confirmed"))}


def evaluate(ws, metrics: Dict, rules: List[Dict]) -> List[Dict]:
    """계산·구조 조항은 코드로 판정하고, 판단 조항은 '판정 전'으로 둔다."""
    rows = []
    for r in rules:
        if r["type"] == "계산":
            m = r.get("metric")
            if m not in metrics or r.get("op") not in OPS:
                rows.append(_row(r, "확인 필요", f"계산할 수 없는 지표 {m}", "코드"))
                continue
            ok = OPS[r["op"]](metrics[m], r["value"])
            rows.append(_row(r, "지킴" if ok else "위반",
                             f"현재 {m}={metrics[m]:g} (기준 {r['value']:g} {OP_TEXT[r['op']]})", "코드"))
        elif r["type"] == "구조":
            fn = STRUCTURE.get(r.get("check", ""))
            if not fn:
                rows.append(_row(r, "확인 필요", f"알 수 없는 구조 점검 {r.get('check')}", "코드"))
                continue
            ok, evidence = fn(ws, r)
            rows.append(_row(r, "확인 필요" if ok is None else ("지킴" if ok else "위반"), evidence, "코드"))
        else:
            rows.append(_row(r, "확인 필요", "판정 전 (finish 때 별도 심사 AI가 판정)", "AI"))
    return rows

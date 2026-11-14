"""코드 관문: 숫자·순서·연결을 AI가 아니라 코드가 확인한다 (원칙 p1).

결과 단계
- FAIL: 고쳐야 finish 가능
- WARN: 고치길 권장
- UNVERIFIED: 팀이 아직 확인하지 않은 운영 규정 조항 위반. 막지 않고 대조표에 표시한다
"""
from typing import Dict, List

from . import rulebook
from .workspace import Workspace

NON_MAJOR_WARN_RATIO = 50  # 비전공자 비율(%)이 이 이상이면 초반 기초 교과를 확인
BASIC_WITHIN_WEEKS = 4

# 운영 규정 조항(키) → 같은 문제를 이미 알리는 점검 코드
COVERED = {"skill_targets": "skill_targets", "periodic_assessment": "quiz_missing", "proficiency_methods": "proficiency_methods",
           "company_tasks_linked": "company_task", "project_ratio": "project_ratio", "total_hours": "total_hours"}

OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, "==": lambda a, b: abs(a - b) < 1e-6}


def metrics(ws: Workspace) -> Dict[str, float]:
    subs = ws.cur.subjects
    total = sum(s.hours for s in subs)
    online = sum(s.hours for s in subs if s.mode == "원격")
    sched = ws.schedule()
    return {
        "total_hours": total,
        "project_ratio": round(sum(s.project_hours for s in subs) / total, 3) if total else 0,
        "online_ratio": round(online / total, 3) if total else 0,
        "max_subject_hours": max((s.hours for s in subs), default=0),
        "subject_count": len(subs),
        "daily_hours": ws.inp.course.daily_hours,
        "days_per_week": ws.inp.course.days_per_week,
        "total_weeks": sched["total_weeks"],
        "period_months": round(sched["total_weeks"] * 12 / 52, 1),  # 편성 기준 훈련기간
    }


def _rule(ws: Workspace, rule, m: Dict, level: str, out: List):
    if rule.judge != "계산" or not rule.metric:
        return
    if rule.metric not in m or rule.op not in OPS or rule.value is None:
        out.append({"level": "WARN", "code": "rule_unreadable", "where": rule.id,
                    "message": f"계산 규정 {rule.id}을 검사할 수 없음 (metric/op/value 확인)"})
        return
    if not OPS[rule.op](m[rule.metric], rule.value):
        out.append({"level": level, "code": "rule", "where": rule.id,
                    "message": f"{rule.text}: 현재 {rule.metric}={m[rule.metric]} (기준 {rule.op} {rule.value})"})


def check(ws: Workspace) -> Dict:
    inp, cur = ws.inp, ws.cur
    c = inp.course
    m = metrics(ws)
    out: List[Dict] = []

    def add(level, code, where, message):
        out.append({"level": level, "code": code, "where": where, "message": message})

    if not cur.subjects:
        add("FAIL", "empty", "-", "교과목이 없음")
        return {"pass": False, "metrics": m, "issues": out}

    # 1. 시간 합계와 교과목 내부 시간
    if abs(m["total_hours"] - c.total_hours) > 1e-6:
        add("FAIL", "total_hours", "전체",
            f"교과목 시간 합계 {m['total_hours']}시간 ≠ 총 훈련시간 {c.total_hours}시간 (차이 {m['total_hours'] - c.total_hours:+g})")
    for s in cur.subjects:
        if s.hours <= 0:
            add("FAIL", "zero_hours", s.id, f"{s.title}: 시간이 0")
        if s.category == "프로젝트" and s.project_hours == 0:
            add("WARN", "project_category", s.id, f"{s.title}: 구분은 프로젝트인데 프로젝트 시간이 0")

    # 2. 프로젝트 비율
    if m["project_ratio"] + 1e-6 < inp.project_ratio:
        need = inp.project_ratio * c.total_hours - sum(s.project_hours for s in cur.subjects)
        add("FAIL", "project_ratio", "전체",
            f"프로젝트 비율 {m['project_ratio']:.1%} < 목표 {inp.project_ratio:.0%} (프로젝트 시간 {need:g}시간 더 필요). "
            f"프로젝트 교과목의 category를 '프로젝트'로 하거나 company_task_ids를 연결한 뒤 allocate_hours를 다시 부르세요")

    # 3. 훈련 방식
    if c.training_mode in ("집체", "원격"):
        for s in cur.subjects:
            if s.mode != c.training_mode:
                add("FAIL", "mode", s.id, f"{s.title}: 훈련 방식이 {c.training_mode}인데 {s.mode}로 편성됨")

    # 4. 선수 개념 순서: 앞 교과목에서 배웠거나(개념 태그 또는 교과목 이름) 훈련 대상이 이미 아는 개념이어야 함
    # 수정 모드에서는 이번에 고친 교과목만 검사한다 (요청하지 않은 부분은 그대로 둔다)
    known = {_norm(k): k for k in inp.entry_knowledge}
    for s in cur.subjects:
        missing = [p for p in s.prerequisites if _norm(p) not in known]
        if missing and (not inp.revise_mode or s.id in ws.touched):
            taught = list(known.values())[-20:]
            add("FAIL", "prerequisite", s.id,
                f"{s.title}: 선수 개념 {missing}을 앞에서 가르치지 않음. 앞에서 배운 개념: {taught}. "
                f"선수 개념 이름을 이 목록에 맞추거나, 앞 교과목 concepts_taught에 넣거나, 순서를 바꾸세요")
        known.update({_norm(k): k for k in s.concepts_taught + [s.title]})

    # 5. 협약 기업 과제는 프로젝트로 연결돼야 함
    for t in inp.company_tasks:
        if not any(p.company_task_id == t.id for p in cur.projects):
            add("FAIL", "company_task", t.id, f"협약 기업 과제 '{t.title}'가 어떤 프로젝트에도 연결되지 않음")
    ids = {s.id for s in cur.subjects}
    for p in cur.projects:
        bad = [x for x in p.subject_ids if x not in ids]
        if bad or not p.subject_ids:
            add("FAIL", "project_link", p.id, f"프로젝트 '{p.title}'의 교과목 연결 확인 (없는 id: {bad})")

    # 6. 학습 목표 연결
    if not cur.learning_goals:
        add("FAIL", "goals", "-", "학습 목표가 없음 (set_plan)")
    for g in cur.learning_goals:
        if not any(g.id in s.linked_goals for s in cur.subjects):
            add("WARN", "goal_unlinked", g.id, f"학습 목표 '{g.text}'에 연결된 교과목이 없음")

    # 7. 단원 설계
    if inp.wants_units:
        for s in cur.subjects:
            if not s.units:
                add("FAIL", "units_missing", s.id, f"{s.title}: 단원 설계가 없음")
            elif abs(sum(u.hours for u in s.units) - s.hours) > 1e-6:
                add("FAIL", "units_hours", s.id,
                    f"{s.title}: 단원 시간 합계 {sum(u.hours for u in s.units):g} ≠ 교과목 시간 {s.hours:g}")

    # 8-1. 수정 모드: 강사가 고른 보완점의 교과목은 반드시 손봐야 함
    for sid in inp.revision_targets:
        if ws.subject(sid) and sid not in ws.touched:
            add("FAIL", "revision_target", sid, f"{ws.subject(sid).title}: 강사가 고른 보완점의 교과목인데 고치지 않음")

    # 8. 수정 모드: 페르소나 점수가 낮은 교과목은 반드시 손봐야 함
    for sid, info in weak_subjects(inp).items():
        if ws.subject(sid) and sid not in ws.touched:
            add("FAIL", "weak_subject", sid,
                f"{info['title'] or sid}: 페르소나 점수가 기준 미만인데 고치지 않음 ({info['detail']})")

    # 9. 기간: 편성이 입력한 기간(개월) 안에 들어가야 함
    if inp.weeks and m["total_weeks"] > inp.weeks:
        add("FAIL", "period", "전체",
            f"편성이 {m['total_weeks']}주인데 기간은 {c.months:g}개월(약 {inp.weeks:g}주). 1일·주 훈련시간 또는 총 시간을 확인하세요")

    # 10. 필수 교과목: 교과목 이름에 핵심 단어가 들어 있으면 인정
    titles = [s.title for s in cur.subjects]
    for req in inp.required_subjects:
        if not matches_required(req, titles):
            add("FAIL", "required_subject", req, f"필수 교과목 '{req}'이 편성표에 없음 (교과목 이름에 핵심 단어가 들어가야 함)")

    # 11. 비전공자 비율이 높으면 앞 4주 안에 선수 개념이 필요 없는 기초 교과가 있어야 함
    if inp.non_major_ratio is not None and inp.non_major_ratio >= NON_MAJOR_WARN_RATIO:
        weeks = {w["id"]: w for w in ws.schedule()["weeks"]}
        basic = [s for s in cur.subjects if s.category != "프로젝트" and not s.prerequisites
                 and weeks.get(s.id, {}).get("week_start", 99) <= BASIC_WITHIN_WEEKS]
        if not basic:
            add("WARN", "non_major_basic", "전체",
                f"비전공자 {inp.non_major_ratio:g}%인데 앞 {BASIC_WITHIN_WEEKS}주 안에 선수 개념이 필요 없는 기초 교과가 없음")

    # 12. 숙련목표·퀴즈·숙련도 향상 방법 (만들어야 하는 결과물)
    # 수정 모드에서 예전 커리큘럼(숙련목표·퀴즈 없음)은 억지로 다시 만들지 않도록 경고만 한다
    need = "WARN" if inp.revise_mode and ws.legacy else "FAIL"
    if not cur.skill_targets:
        add(need, "skill_targets", "-", "숙련목표가 없음 (set_skill_targets)")
    for t in cur.skill_targets:
        if not t.subject_ids:
            add("WARN", "skill_target_unlinked", t.id, f"숙련목표 '{t.text}'에 연결된 교과목이 없음")
    for s in cur.subjects:
        if s.category == "프로젝트":
            continue
        n = sum(len(q.questions) for q in cur.quizzes if q.subject_id == s.id)
        if n < rulebook.QUIZ_MIN_QUESTIONS:
            add(need, "quiz_missing", s.id,
                f"{s.title}: 객관식 퀴즈 {n}문항 (최소 {rulebook.QUIZ_MIN_QUESTIONS}문항, write_quiz)")
    ids = {s.id for s in cur.subjects}
    sched = {w["id"]: w for w in ws.schedule()["weeks"]}
    for q in cur.quizzes:
        if q.subject_id not in ids:
            add("WARN", "quiz_orphan", q.id, f"퀴즈 {q.id}의 교과목 {q.subject_id}이 없음")
        elif q.week and not sched[q.subject_id]["week_start"] <= q.week <= sched[q.subject_id]["week_end"]:
            add("WARN", "quiz_week", q.id, f"퀴즈 {q.id}의 {q.week}주차가 교과목 기간을 벗어남 (시간이 바뀌었으면 다시 쓰세요)")
    for sid in sorted(ws.quiz_stale & ids):
        add("WARN", "quiz_stale", sid, f"{ws.subject(sid).title}: 퀴즈를 쓴 뒤 교과목 내용이 바뀜. 바뀐 내용에 맞게 write_quiz로 다시 쓰세요")
    assessed = {x for q in cur.quizzes for qq in q.questions for x in qq.skill_target_ids}
    for t in cur.skill_targets:
        if cur.quizzes and t.id not in assessed:
            add("WARN", "skill_unassessed", t.id, f"숙련목표 {t.id}를 확인하는 퀴즈 문항이 없음 (skill_target_ids 연결)")
    if cur.quizzes:
        gap, where = rulebook.max_gap(ws)
        if gap > rulebook.ASSESSMENT_GAP_WEEKS:
            add("WARN", "assessment_gap", where,
                f"평가 없이 {gap}주 ({where})가 지나감. 긴 교과목에는 week를 정해 중간 퀴즈를 추가하세요")
    if not cur.proficiency_methods:
        add(need, "proficiency_methods", "-", "숙련도 향상 방법이 없음 (set_proficiency_methods)")

    # 13. 운영 규정 조항: 계산·구조 조항을 코드로 대조. 팀이 확인한 조항 위반은 FAIL, 확인 전 조항은 UNVERIFIED
    rows = rulebook.evaluate(ws, m, rulebook.load_rules(c.business_profile, c.training_mode))
    for r in rows:
        if r["by"] != "코드" or r["verdict"] == "지킴":
            continue
        level = ("FAIL" if r["confirmed"] else "UNVERIFIED") if r["verdict"] == "위반" else "WARN"
        same = [i for i in out if i["code"] == COVERED.get(r["key"])]  # 위에서 이미 같은 문제를 알린 경우 겹치지 않게
        if same and (level != "FAIL" or any(i["level"] == "FAIL" for i in same)):
            continue
        add(level, "regulation", r["id"], f"[{r['article']}] {r['text']}: {r['evidence']}")
    # 입력으로 받은 확인된 규정 (CLI 입력의 confirmed_rules)
    for r in inp.confirmed_rules:
        _rule(ws, r, m, "FAIL" if r.grade in ("필수", "조건부") else "WARN", out)

    return {"pass": not any(i["level"] == "FAIL" for i in out), "metrics": m, "issues": out, "regulations": rows}


def _norm(text: str) -> str:
    return "".join(text.lower().split())


def matches_required(req: str, titles) -> bool:
    """필수 교과목 판정: 이름이 통째로 들어 있거나, 핵심 단어(2글자 이상)의 절반 이상이 한 교과목 이름에 있으면 인정."""
    words = [w.lower() for w in req.split() if len(w) >= 2]
    for t in titles:
        low = t.lower()
        if _norm(req) in _norm(t):
            return True
        if words and sum(w in low for w in words) * 2 >= len(words):
            return True
    return False


def weak_subjects(inp) -> Dict[str, Dict]:
    """페르소나 중 하나라도 기준 점수 미만인 교과목."""
    fb = inp.persona_feedback
    if not fb or not inp.previous_curriculum:
        return {}
    titles = {s.get("id"): s.get("title", "") for s in inp.previous_curriculum.get("subjects", [])}
    weak: Dict[str, Dict] = {}
    for p in fb.personas:
        for sc in p.subjects:
            if sc.score < fb.pass_score:
                w = weak.setdefault(sc.subject_id, {"title": titles.get(sc.subject_id, ""), "detail": "", "items": []})
                w["items"].append({"persona": p.persona, "score": sc.score, "note": sc.note})
    for w in weak.values():
        w["detail"] = ", ".join(f"{i['persona']} {i['score']:g}점" for i in w["items"])
    return weak

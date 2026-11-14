"""앱 화면 입력(Survey + 신청 서류) <-> 생성 agent(generator_agent) 형식 변환."""
import math
import re
from typing import Dict, List

from generator_agent.schemas import CompanyTask, CourseInfo, DraftInfo, GenerationInput

from .base import AIContext


def to_generation_input(ctx: AIContext) -> GenerationInput:
    s = ctx.survey
    announcement = "\n\n".join(t for t in (ctx.application_docs, ctx.criteria) if t and t.strip())
    return GenerationInput(
        draft=DraftInfo(owner=s.owner),
        outputs=["편성표"],
        course=CourseInfo(
            business_profile=s.funding or "KDT",
            field=s.subject,
            total_hours=s.total_hours or 0,
            daily_hours=s.daily_hours or 8,
            days_per_week=s.days_per_week or 5,
            months=s.months or 0,
            training_mode=s.training_mode or "집체",
        ),
        target_learners=s.target_desc or s.target,
        non_major_ratio=s.non_major_ratio,
        prior_experience=[x.strip() for x in s.prior_experience.split(",") if x.strip()],
        learner_goal=s.learner_goal,
        purpose=s.intent,
        announcement_text=announcement,
        project_ratio=(s.project_ratio if s.project_ratio is not None else 30) / 100,
        required_subjects=s.required_subjects,
        company_tasks=[CompanyTask(id=f"T{i + 1}", company=t.company, title=t.title)
                       for i, t in enumerate(s.company_tasks)],
        pass_score=s.pass_score if s.pass_score is not None else 3.1,
        budget_krw=s.budget_krw if s.budget_krw is not None else 2000,
    )


def _period(w: Dict) -> str:
    if not w:
        return ""
    a, b = w["week_start"], w["week_end"]
    return f"{a}주차" if a == b else f"{a}~{b}주차"


def to_app_curriculum(cur: Dict, ctx: AIContext) -> Dict:
    """생성 agent 결과(교과목 편성표)를 앱의 Curriculum 형식(모듈)으로 바꾼다."""
    s, meta, sched, report = ctx.survey, cur["meta"], cur["schedule"], cur["check_report"]
    weeks = {w["id"]: w for w in sched.get("weeks", [])}
    subjects = {x["id"]: x for x in cur["subjects"]}

    modules = []
    for x in cur["subjects"]:
        hours = x["theory_hours"] + x["practice_hours"] + x["project_hours"]
        split = " / ".join(f"{k} {v:g}시간" for k, v in
                           (("이론", x["theory_hours"]), ("실습", x["practice_hours"]), ("프로젝트", x["project_hours"])) if v)
        practice = "; ".join(filter(None, [f"[{x['category']}] {split}", x.get("assessment") and f"평가: {x['assessment']}"]))
        modules.append({"period": _period(weeks.get(x["id"])), "title": x["title"], "hours": round(hours),
                        "objectives": x["goals"], "topics": x["topics"], "practice": practice,
                        "prerequisites": x["prerequisites"], "rationale": x.get("rationale", "")})

    projects = []
    for p in cur["projects"]:
        linked = [weeks[i] for i in p["subject_ids"] if i in weeks and subjects.get(i, {}).get("category") == "프로젝트"]
        period = _period({"week_start": min(w["week_start"] for w in linked), "week_end": max(w["week_end"] for w in linked)}) if linked else ""
        desc = " ".join(filter(None, [p.get("description"), p.get("portfolio_output") and f"산출물: {p['portfolio_output']}"]))
        projects.append({"name": p["title"], "period": period, "description": desc})

    m = report.get("metrics", {})
    notes: List[str] = [
        f"[코드 점검 {'통과' if report.get('pass') else '미통과'}] 총 {m.get('total_hours', 0):g}시간 · {sched.get('total_weeks')}주 · "
        f"프로젝트 비율 {m.get('project_ratio', 0):.0%} (하한 {(s.project_ratio if s.project_ratio is not None else 30)}%)",
    ]
    if s.required_subjects:
        notes.append("필수 교과목 포함 확인: " + ", ".join(s.required_subjects))
    for p in cur["projects"]:
        if p.get("company_task_id"):
            notes.append(f"협약기업 과제 {p['company_task_id']} → 프로젝트 '{p['title']}'")
    if cur.get("compliance"):
        count = lambda v: sum(r["verdict"] == v for r in cur["compliance"])
        notes.append(f"운영 규정 대조 {len(cur['compliance'])}개 조항: 지킴 {count('지킴')} · 위반 {count('위반')} · 확인 필요 {count('확인 필요')}")
    notes += [f"참고한 운영 규정: {r['source']} {r['article']}" for r in cur.get("regulation_notes", [])]
    notes += [f"[{i['level']}] {i['message']}" for i in report.get("issues", [])]
    if meta.get("unresolved"):
        notes.append(f"[못 고친 문제] {meta['unresolved']}")
    notes.append(f"생성 agent: {meta.get('model') or meta.get('provider')} · {meta.get('steps')}단계 · "
                 f"{meta.get('seconds')}초 · 약 {meta.get('cost_krw', 0):g}원 · 종료: {meta.get('stop_reason')}")

    change_log = [f"{c['target']} {c['action']}: {c['reason']}" for c in cur.get("change_log", [])
                  if c.get("source") != "시간 배분" or meta.get("mode") == "수정"]
    assessments = list(dict.fromkeys(x["assessment"] for x in cur["subjects"] if x.get("assessment")))
    quizzes = []
    for q in cur.get("quizzes", []):
        sub = subjects.get(q["subject_id"], {})
        quizzes.append({**q, "subject_title": sub.get("title", ""),
                        "week": q.get("week") or weeks.get(q["subject_id"], {}).get("week_end")})
    if quizzes:
        n = sum(len(q["questions"]) for q in quizzes)
        qweeks = sorted({q["week"] for q in quizzes if q["week"]})
        assessments.insert(0, f"교과목별 객관식 퀴즈 {len(quizzes)}회·{n}문항 ({', '.join(map(str, qweeks))}주차)")
    target = s.target_desc or s.target
    if s.non_major_ratio is not None:
        target += f" (비전공자 {s.non_major_ratio}%)"
    design = [f"교육 목적 해석: {cur['intent_summary']}"] if cur.get("intent_summary") else []
    allocation = [c["reason"] for c in cur.get("change_log", []) if c.get("source") == "시간 배분"]
    if allocation:
        design.append(f"시간 배분: {allocation[-1]}")
    if m:
        design.append(f"프로젝트 비율 {m.get('project_ratio', 0):.0%}, 교과목 {m.get('subject_count', len(modules))}개, "
                      f"{sched.get('total_weeks')}주 — 숫자는 코드가 계산하고 점검했어요")
    return {
        "title": s.subject and f"{s.subject} 과정" or "커리큘럼",
        "design_rationale": design,
        "summary": " ".join(filter(None, [cur.get("intent_summary"), meta.get("summary")])),
        "target_summary": target,
        "total_weeks": sched.get("total_weeks"),
        "total_hours": round(sched.get("total_hours") or 0),
        "learning_goals": [g["text"] for g in cur["learning_goals"]],
        "modules": modules,
        "projects": projects,
        "assessment": " / ".join(assessments),
        "compliance_notes": notes,
        "skill_targets": cur.get("skill_targets", []),
        "quizzes": quizzes,
        "proficiency_methods": cur.get("proficiency_methods", []),
        "compliance_table": cur.get("compliance", []),
        "change_log": change_log if meta.get("mode") == "수정" else [],
        "agent_curriculum": cur,  # 수정·검증 agent가 개념 태그까지 그대로 쓰도록 원본을 함께 보관
    }


# ---------- 수정 모드: 앱 커리큘럼 → 생성 agent의 기존 커리큘럼 ----------

def _num(pattern: str, text: str) -> float:
    m = re.search(pattern, text or "")
    return float(m.group(1)) if m else 0


def to_agent_curriculum(app_cur: Dict) -> Dict:
    """생성 agent 원본이 있으면 그대로, 없으면(예전 방식·붙여넣기) 모듈을 교과목으로 바꾼다."""
    if app_cur.get("agent_curriculum"):
        return app_cur["agent_curriculum"]
    subjects = []
    for i, m in enumerate(app_cur.get("modules", [])):
        hours = float(m.get("hours") or 0)
        practice = m.get("practice", "") or ""
        project = "프로젝트" in m.get("title", "") or practice.startswith("[프로젝트]")
        theory = 0.0 if project else (_num(r"이론 (\d+(?:\.\d+)?)시간", practice) or round(hours * 0.3))
        subjects.append({
            "id": f"S{i + 1:02d}", "title": m.get("title", ""), "category": "프로젝트" if project else "실습",
            "theory_hours": theory, "practice_hours": 0 if project else hours - theory, "project_hours": hours if project else 0,
            "goals": m.get("objectives", []), "topics": m.get("topics", []), "concepts_taught": m.get("topics", []),
            "prerequisites": m.get("prerequisites", []),
            "assessment": (re.search(r"평가: (.+)$", practice) or [None, practice])[1] if practice else "",
        })
    return {"intent_summary": app_cur.get("summary", ""),
            "learning_goals": [{"id": f"G{i + 1}", "text": g} for i, g in enumerate(app_cur.get("learning_goals", []))],
            "subjects": subjects, "projects": []}


def revision_input(ctx: AIContext, app_cur: Dict, request: str = "", gaps: List[Dict] = ()) -> GenerationInput:
    """수정 모드 입력. 불러온 커리큘럼은 과정 정보가 비어 있을 수 있어 기존 커리큘럼에서 채운다."""
    prev = to_agent_curriculum(app_cur)
    inp = to_generation_input(ctx)
    c = inp.course
    total = sum(x["theory_hours"] + x["practice_hours"] + x["project_hours"] for x in prev["subjects"])
    if not c.total_hours:
        c.total_hours = round(total) or (app_cur.get("total_hours") or 0)
    if not c.months:
        weeks = math.ceil(c.total_hours / (c.daily_hours * c.days_per_week)) if c.total_hours else (app_cur.get("total_weeks") or 0)
        c.months = math.ceil(weeks * 12 / 52 * 2) / 2
    if ctx.survey.project_ratio is None and total:  # 예전 커리큘럼을 억지로 재편성하지 않도록 지금 비율을 넘지 않게
        inp.project_ratio = min(0.3, sum(x["project_hours"] for x in prev["subjects"]) / total)
    titles = {x["title"]: x["id"] for x in prev["subjects"]}
    targets = []
    for g in gaps:
        loc = (g.get("location") or "").split(" (")[0].strip()
        sid = titles.get(loc) or next((v for k, v in titles.items() if loc and (loc in k or k in loc)), None)
        if sid and sid not in targets:
            targets.append(sid)
    inp.previous_curriculum = prev
    inp.revision_request = request
    inp.revision_items = [f"[{g.get('severity', '')}] {g.get('location', '')}: {g.get('issue', '')} → {g.get('suggestion', '')}"
                          + (f" ({g['persona']})" if g.get("persona") else "") for g in gaps]
    inp.revision_targets = targets
    return inp


def request_for_validator(ctx: AIContext) -> Dict:
    """검증 agent가 생성 agent 원본을 학생용 보기로 바꿀 때 쓰는 과정·학습자 정보."""
    s = ctx.survey
    return {"course": {"field": s.subject, "daily_hours": s.daily_hours or 8, "days_per_week": s.days_per_week or 5,
                       "training_mode": s.training_mode}, "target_learners": s.target_desc or s.target}

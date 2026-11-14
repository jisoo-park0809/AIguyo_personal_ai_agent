"""커리큘럼을 학생용 보기로 바꾼다. 설계 의도·배분 이유·규정 메모·점검 결과는 넘기지 않는다 (p3)."""
import re
from typing import Dict, List, Optional

from .schemas import StudentView, ViewProject, ViewSubject


def _questions(quiz: Dict) -> List[Dict]:
    """학생에게는 문제와 보기만 보여 준다 (정답·해설·숙련목표 연결은 뺌)."""
    return [{"question": q["question"], "choices": q["choices"]} for q in quiz.get("questions", [])]


def from_generator(cur: Dict, request: Optional[Dict] = None) -> StudentView:
    """생성 agent 결과(generator_agent) → 학생용 보기. request는 생성 agent 입력(과정·학습자 정보)."""
    req = request or {}
    course = req.get("course", {})
    weeks = {w["id"]: w for w in cur.get("schedule", {}).get("weeks", [])}
    subjects = [
        ViewSubject(
            id=s["id"], title=s["title"], category=s.get("category", ""),
            week_start=weeks.get(s["id"], {}).get("week_start", 0), week_end=weeks.get(s["id"], {}).get("week_end", 0),
            hours=s["theory_hours"] + s["practice_hours"] + s["project_hours"],
            theory_hours=s["theory_hours"], practice_hours=s["practice_hours"], project_hours=s["project_hours"],
            goals=s.get("goals", []), topics=s.get("topics", []), prerequisites=s.get("prerequisites", []),
            assessment=s.get("assessment", ""), concepts=s.get("concepts_taught", []),
        )
        for s in cur.get("subjects", [])
    ]
    projects = []
    for p in cur.get("projects", []):
        linked = [weeks[i] for i in p.get("subject_ids", []) if i in weeks]
        period = f"{min(w['week_start'] for w in linked)}~{max(w['week_end'] for w in linked)}주차" if linked else ""
        projects.append(ViewProject(name=p["title"], period=period, deliverable=p.get("portfolio_output", "")))
    return StudentView(
        field=course.get("field") or cur.get("meta", {}).get("field", ""),
        total_hours=cur.get("schedule", {}).get("total_hours", 0),
        total_weeks=cur.get("schedule", {}).get("total_weeks", 0),
        daily_hours=course.get("daily_hours", 8), days_per_week=course.get("days_per_week", 5),
        training_mode=course.get("training_mode", ""),
        target=req.get("target_learners", ""),
        learning_goals=[g["text"] for g in cur.get("learning_goals", [])],
        subjects=subjects, projects=projects,
        quizzes={sid: qs for sid, qs in _group(cur.get("quizzes", []), lambda q: q["subject_id"]).items()},
    )


def _group(quizzes: List[Dict], key) -> Dict[str, List[Dict]]:
    out: Dict[str, List[Dict]] = {}
    for q in quizzes:
        k = key(q)
        if k:
            out.setdefault(k, []).extend(_questions(q))
    return out


def _weeks(period: str):
    nums = [int(n) for n in re.findall(r"\d+", period or "")]
    return (nums[0], nums[-1]) if nums else (0, 0)


def from_app(curriculum: Dict, survey) -> StudentView:
    """앱의 커리큘럼(모듈) → 학생용 보기. survey는 app.schemas.Survey."""
    subjects = []
    for i, m in enumerate(curriculum.get("modules", [])):
        a, b = _weeks(m.get("period", ""))
        practice = m.get("practice", "") or ""
        category = "프로젝트" if "프로젝트" in (m.get("title", "") + practice[:12]) else ""
        subjects.append(ViewSubject(
            id=f"M{i + 1:02d}", title=m.get("title", ""), category=category, week_start=a, week_end=b,
            hours=m.get("hours") or 0, goals=m.get("objectives", []), topics=m.get("topics", []),
            prerequisites=m.get("prerequisites", []), assessment=practice,
        ))
    projects = [ViewProject(name=p.get("name", ""), period=p.get("period", ""), deliverable=p.get("description", ""))
                for p in curriculum.get("projects", [])]
    return StudentView(
        field=getattr(survey, "subject", "") or curriculum.get("title", ""),
        total_hours=curriculum.get("total_hours") or sum(s.hours for s in subjects),
        total_weeks=curriculum.get("total_weeks") or max((s.week_end for s in subjects), default=0),
        daily_hours=getattr(survey, "daily_hours", None) or 8, days_per_week=getattr(survey, "days_per_week", None) or 5,
        training_mode=getattr(survey, "training_mode", "") or "",
        target=getattr(survey, "target_desc", "") or curriculum.get("target_summary", ""),
        learning_goals=curriculum.get("learning_goals", []),
        subjects=subjects, projects=projects,
        quizzes=_group(curriculum.get("quizzes", []),
                       lambda q: next((s.id for s in subjects if s.title == q.get("subject_title")), "")),
    )

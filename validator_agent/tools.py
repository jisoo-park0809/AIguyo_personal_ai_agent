"""학생 페르소나 agent가 고를 수 있는 tool. 커리큘럼을 고치는 tool은 없다 (고치는 건 생성 agent의 일)."""
import math
from typing import Any, Dict, List, Set

from .schemas import SCORE_ITEMS, PersonaCard, StudentView

_WHY = {"type": "string", "description": "지금 이 tool을 부르는 이유 한 줄"}


def _fn(name: str, description: str, properties: Dict, required: List[str] = ()) -> Dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": {"why": _WHY, **properties}, "required": ["why"] + list(required)}}}


TOOL_SPECS = [
    _fn("get_my_profile", "내 페르소나 카드(배경, 아는 것, 모르는 것, 하루 복습 가능 시간)를 본다. 처음에 쓴다.", {}),
    _fn("view_course", "과정 개요와 교과목 목록(주차·시간)을 본다.", {}),
    _fn("view_subject", "교과목 하나의 상세(목표, 주제, 선수 지식, 평가, 이론·실습·프로젝트 시간)를 본다.",
        {"subject_id": {"type": "string"}}, ["subject_id"]),
    _fn("view_quiz", "교과목의 객관식 퀴즈(문제와 보기, 정답은 없음)를 본다. 퀴즈가 있는 교과목은 일지를 쓰기 전에 보고, "
        "내 수준에서 풀 수 있을지 판단한다.", {"subject_id": {"type": "string"}}, ["subject_id"]),
    _fn("check_prerequisites", "이 교과목의 선수 지식 중 앞 교과목에서 배우지 않았고, 내가 모르는 것을 확인한다. 어려워 보일 때 쓴다.",
        {"subject_id": {"type": "string"}}, ["subject_id"]),
    _fn("estimate_workload", "그 주에 듣는 수업 시간, 겹치는 교과목 수, 새로 나오는 주제 수와 내 복습 가능 시간을 본다. 학습량이 걱정될 때 쓴다.",
        {"week": {"type": "integer"}}, ["week"]),
    _fn("compare_subjects", "두 교과목의 주제가 얼마나 겹치는지 본다. '또 배우네?' 싶을 때 쓴다.",
        {"subject_a": {"type": "string"}, "subject_b": {"type": "string"}}, ["subject_a", "subject_b"]),
    _fn("write_journal", "교과목을 들은 뒤 수강 일지를 쓴다. 모든 교과목에 하나씩 써야 끝낼 수 있다.",
        {"subject_id": {"type": "string"},
         "understanding": {"type": "string", "enum": ["상", "중", "하"], "description": "내 수준에서의 이해도"},
         "blocked_reason": {"type": "string", "description": "막힌 이유 (없으면 비움)"},
         "workload": {"type": "string", "enum": ["적정", "많음", "적음"]},
         "feeling": {"type": "string", "description": "이 교과목을 들은 뒤의 기분 한 줄"},
         "quiz_fit": {"type": "string", "enum": ["쉬움", "적절", "어려움"],
                      "description": "퀴즈가 있는 교과목만: 이 교과목을 들은 내 수준에서 퀴즈 난이도"},
         "quiz_note": {"type": "string", "description": "퀴즈 난이도를 그렇게 본 이유 (어느 문항이 왜)"}},
        ["subject_id", "understanding", "workload"]),
    _fn("report_gap", "이 학생에게 문제가 되는 부분을 보고한다. 위치(교과목 id)가 없으면 거부된다.",
        {"subject_id": {"type": "string"}, "issue": {"type": "string", "description": "무엇이 문제인지"},
         "reason": {"type": "string", "description": "왜 이 학생에게 문제인지"},
         "severity": {"type": "string", "enum": ["높음", "중간", "낮음"],
                      "description": "높음=이탈·수료 불가 위험, 중간=학습 효과가 크게 떨어짐, 낮음=고치면 더 좋음"},
         "suggestion": {"type": "string", "description": "어떻게 바꾸면 좋을지"}},
        ["subject_id", "issue", "reason", "severity", "suggestion"]),
    _fn("finish", "평가를 끝내고 항목별 점수(1~5)와 수료 가능성을 낸다. 모든 교과목에 일지가 있어야 끝난다.",
        {"scores": {"type": "object", "description": "difficulty(난이도), workload(학습량), flow(흐름), career(목표 연결), motivation(동기) 각 1~5",
                    "properties": {k: {"type": "integer"} for k in SCORE_ITEMS}, "required": SCORE_ITEMS},
         "completion": {"type": "string", "enum": ["가능", "위험", "불가"]},
         "summary": {"type": "string", "description": "이 학생 입장의 총평 2문장"}},
        ["scores", "completion", "summary"]),
]


def norm(text: str) -> str:
    return "".join(str(text).lower().split())


def _match(term: str, pool: Set[str]) -> bool:
    t = norm(term)
    return any(t and (t in p or p in t) for p in pool if p)


class PersonaToolBox:
    def __init__(self, view: StudentView, persona: PersonaCard):
        self.view, self.persona = view, persona
        self.subjects = {s.id: s for s in view.subjects}
        self.order = [s.id for s in view.subjects]
        self.journal: Dict[str, Dict] = {}
        self.gaps: List[Dict] = []
        self.finished = False
        self.result: Dict[str, Any] = {}

    def call(self, name: str, args: Dict[str, Any]) -> Dict:
        fn = getattr(self, "t_" + name, None)
        if not fn:
            return {"ok": False, "error": f"없는 tool: {name}"}
        try:
            return fn(**args)
        except TypeError as e:
            return {"ok": False, "error": f"인자 오류: {e}"}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ---------- 코드가 계산하는 사실 ----------

    def taught_before(self, sid: str) -> Set[str]:
        pool: Set[str] = set()
        for x in self.order:
            if x == sid:
                break
            s = self.subjects[x]
            pool |= {norm(c) for c in (s.concepts or []) + s.topics + [s.title]}
        return pool

    def prereq_facts(self, sid: str) -> Dict:
        s = self.subjects[sid]
        taught = self.taught_before(sid)
        not_taught = [p for p in s.prerequisites if not _match(p, taught)]
        knows_all = "*" in self.persona.known_terms
        known = {norm(k) for k in self.persona.known_terms if k != "*"}
        dont_know = [] if knows_all else [p for p in not_taught if not _match(p, known)]
        return {"prerequisites": s.prerequisites, "not_taught_before": not_taught, "i_dont_know": dont_know}

    # ---------- 보기 ----------

    def t_get_my_profile(self) -> Dict:
        return self.persona.model_dump(exclude={"group"})

    def t_view_course(self) -> Dict:
        v = self.view
        return {"field": v.field, "total_hours": v.total_hours, "total_weeks": v.total_weeks,
                "hours_per_week": v.daily_hours * v.days_per_week, "training_mode": v.training_mode, "target": v.target,
                "learning_goals": v.learning_goals,
                "subjects": [{"id": s.id, "title": s.title, "weeks": f"{s.week_start}~{s.week_end}", "hours": s.hours,
                              "category": s.category} for s in v.subjects],
                "projects": [p.model_dump() for p in v.projects]}

    def t_view_subject(self, subject_id: str) -> Dict:
        s = self.subjects.get(subject_id)
        if not s:
            return {"ok": False, "error": f"교과목 {subject_id} 없음", "ids": self.order}
        return {**s.model_dump(), "quiz_questions": len(self.view.quizzes.get(subject_id, []))}

    def t_view_quiz(self, subject_id: str) -> Dict:
        if subject_id not in self.subjects:
            return {"ok": False, "error": f"교과목 {subject_id} 없음", "ids": self.order}
        qs = self.view.quizzes.get(subject_id, [])
        if not qs:
            return {"ok": True, "questions": [], "message": "이 교과목에는 퀴즈가 없음"}
        return {"ok": True, "questions": [{"no": i + 1, **q} for i, q in enumerate(qs)]}

    def t_check_prerequisites(self, subject_id: str) -> Dict:
        if subject_id not in self.subjects:
            return {"ok": False, "error": f"교과목 {subject_id} 없음"}
        return self.prereq_facts(subject_id)

    def t_estimate_workload(self, week: int) -> Dict:
        v = self.view
        active = [s for s in v.subjects if s.week_start <= week <= max(s.week_end, s.week_start)]
        new_topics = sum(len(s.topics) for s in v.subjects if s.week_start == week)
        return {"week": week, "class_hours": v.daily_hours * v.days_per_week,
                "subjects_this_week": [s.title for s in active], "new_topics": new_topics,
                "my_review_hours_per_week": self.persona.review_hours_per_day * v.days_per_week}

    def t_compare_subjects(self, subject_a: str, subject_b: str) -> Dict:
        a, b = self.subjects.get(subject_a), self.subjects.get(subject_b)
        if not a or not b:
            return {"ok": False, "error": "교과목 id 확인", "ids": self.order}
        ta, tb = {norm(t): t for t in a.topics}, {norm(t): t for t in b.topics}
        same = [ta[k] for k in ta if any(k in j or j in k for j in tb)]
        ratio = len(same) / max(min(len(ta), len(tb)), 1)
        return {"overlapping_topics": same, "overlap_ratio": round(ratio, 2)}

    # ---------- 기록 ----------

    def t_write_journal(self, subject_id: str, understanding: str, workload: str,
                        blocked_reason: str = "", feeling: str = "", quiz_fit: str = "", quiz_note: str = "") -> Dict:
        if subject_id not in self.subjects:
            return {"ok": False, "error": f"교과목 {subject_id} 없음", "ids": self.order}
        if understanding not in ("상", "중", "하"):
            return {"ok": False, "error": "understanding은 상/중/하"}
        has_quiz = bool(self.view.quizzes.get(subject_id))
        if has_quiz and quiz_fit not in ("쉬움", "적절", "어려움"):
            return {"ok": False, "error": "이 교과목에는 퀴즈가 있음. view_quiz로 보고 quiz_fit(쉬움/적절/어려움)을 적으세요"}
        self.journal[subject_id] = {"subject_id": subject_id, "title": self.subjects[subject_id].title,
                                    "understanding": understanding, "workload": workload,
                                    "blocked_reason": blocked_reason, "feeling": feeling,
                                    "quiz_fit": quiz_fit if has_quiz else "", "quiz_note": quiz_note if has_quiz else ""}
        left = [x for x in self.order if x not in self.journal]
        return {"ok": True, "remaining": left}

    def t_report_gap(self, subject_id: str, issue: str, reason: str, severity: str, suggestion: str) -> Dict:
        if subject_id not in self.subjects:
            return {"ok": False, "error": "위치(교과목 id)가 올바르지 않아 보고할 수 없음", "ids": self.order}
        if severity not in ("높음", "중간", "낮음"):
            return {"ok": False, "error": "severity는 높음/중간/낮음"}
        s = self.subjects[subject_id]
        self.gaps.append({"subject_id": subject_id, "location": f"{s.title} ({s.week_start}~{s.week_end}주차)",
                          "issue": issue, "reason": reason, "severity": severity, "suggestion": suggestion})
        return {"ok": True, "gaps": len(self.gaps)}

    def t_finish(self, scores: Dict, completion: str, summary: str) -> Dict:
        left = [x for x in self.order if x not in self.journal]
        if left:
            return {"ok": False, "error": f"일지가 없는 교과목이 있어 끝낼 수 없음: {left}"}
        bad = [k for k in SCORE_ITEMS if not isinstance(scores.get(k), (int, float)) or not 1 <= scores[k] <= 5]
        if bad:
            return {"ok": False, "error": f"점수는 1~5 정수여야 함: {bad}"}
        if completion not in ("가능", "위험", "불가"):
            return {"ok": False, "error": "completion은 가능/위험/불가"}
        self.result = {"scores": {k: int(math.floor(scores[k] + 0.5)) for k in SCORE_ITEMS},
                       "completion": completion, "summary": summary}
        self.finished = True
        return {"ok": True}

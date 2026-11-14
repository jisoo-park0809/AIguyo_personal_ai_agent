"""학생 검증 agent의 입력·출력 형식."""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

DATA = Path(__file__).resolve().parent / "data"


class PersonaCard(BaseModel):
    id: str
    name: str
    summary: str
    group: str  # major | non_major (비전공자 비율 가중 평균에 사용)
    major: bool
    knowledge: str
    project_experience: str
    known_terms: List[str] = []  # 이미 아는 개념. "*"이면 기초 개념은 모두 안다고 본다
    unknown: List[str] = []
    misconceptions: List[str] = []
    cares_about: str = ""
    review_hours_per_day: float = 2
    dropout_signal: str = ""


def load_personas() -> List[PersonaCard]:
    return [PersonaCard.model_validate(p) for p in json.loads((DATA / "personas.json").read_text(encoding="utf-8"))]


# ---------- 학생용 보기: 학생이 실제로 받는 정보만 (설계 의도·배분 이유·규정 메모는 없음, p3) ----------

class ViewSubject(BaseModel):
    id: str
    title: str
    category: str = ""
    week_start: int = 0
    week_end: int = 0
    hours: float = 0
    theory_hours: float = 0
    practice_hours: float = 0
    project_hours: float = 0
    goals: List[str] = []
    topics: List[str] = []
    prerequisites: List[str] = []
    assessment: str = ""
    concepts: List[str] = []  # 이 교과목에서 배우는 개념 (없으면 이름·주제로 대신)


class ViewProject(BaseModel):
    name: str
    period: str = ""
    deliverable: str = ""


class StudentView(BaseModel):
    field: str = ""
    total_hours: float = 0
    total_weeks: int = 0
    daily_hours: int = 8
    days_per_week: int = 5
    training_mode: str = ""
    target: str = ""
    learning_goals: List[str] = []
    subjects: List[ViewSubject] = []
    projects: List[ViewProject] = []
    quizzes: Dict[str, List[Dict[str, Any]]] = {}  # 교과목 id → 객관식 문항 (정답·해설은 뺌)


class ValidationInput(BaseModel):
    view: StudentView
    non_major_ratio: Optional[float] = None  # 비전공자 비율(%). 가중 평균에 사용
    pass_score: float = 3.1
    rules_pass: Optional[bool] = None  # 생성 단계의 규정 점검 결과 (모르면 None)
    budget_krw: float = 2000
    personas: List[PersonaCard] = []


# ---------- 결과 ----------

UNDERSTANDING_SCORE = {"상": 5, "중": 3, "하": 1}
SEVERITY_WEIGHT = {"높음": 3, "중간": 2, "낮음": 1}
SCORE_ITEMS = ["difficulty", "workload", "flow", "career", "motivation"]
SCORE_LABEL = {"difficulty": "난이도", "workload": "학습량", "flow": "흐름", "career": "목표 연결", "motivation": "동기"}


class RunResult(BaseModel):
    persona_id: str
    run: int
    finished: bool = False
    journal: List[Dict[str, Any]] = []
    gaps: List[Dict[str, Any]] = []
    scores: Dict[str, int] = {}
    completion: str = ""  # 가능 | 위험 | 불가
    summary: str = ""
    fidelity: Dict[str, Any] = {}
    steps: int = 0
    cost_krw: float = 0
    trace: List[Dict[str, Any]] = []

    @property
    def journal_map(self) -> Dict[str, Dict[str, Any]]:
        return {e["subject_id"]: e for e in self.journal}

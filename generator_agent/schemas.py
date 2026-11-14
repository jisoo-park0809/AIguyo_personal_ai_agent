"""생성 agent의 입력·출력 형식."""
from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, Field


# ---------- 입력 ----------

class DraftInfo(BaseModel):
    name: str = ""  # 초안 이름 (나중에 로그인 정보에서 가져옴)
    owner: str = ""  # 담당자
    memo: str = ""  # 검토자에게 남기는 메모
    course_examples: List[str] = []  # 참고할 과정 예시 id (data/examples/courses/<id>.json)


class CourseInfo(BaseModel):
    business_profile: str = "KDT"  # data/business_profiles.json의 키
    field: str = ""  # 분야·직군 (예: 게임 개발 / Unity·C#)
    title: str = ""  # 과정명 (선택)
    total_hours: int
    daily_hours: int = 8
    days_per_week: int = 5
    months: float = 0  # 기간(개월). 0이면 기간 점검을 하지 않음
    training_mode: str = "집체"  # 집체 | 원격 | 혼합


class CompanyTask(BaseModel):
    id: str
    company: str
    title: str
    description: str = ""
    deliverable: str = ""


class SubjectScore(BaseModel):
    subject_id: str
    score: float
    note: str = ""


class PersonaScore(BaseModel):
    persona: str
    avg_score: float
    subjects: List[SubjectScore] = []


class PersonaFeedback(BaseModel):
    """검증 단계에서 받은 학생 페르소나별 점수. 수정 모드에서만 쓴다."""
    scale_max: float = 5
    pass_score: float = 3.1
    personas: List[PersonaScore] = []


class ConfirmedRule(BaseModel):
    """규정 확인 관문(c4e)을 통과한 규정. 계산 규정은 코드가 검사한다."""
    id: str
    text: str
    grade: str = "필수"  # 필수 | 조건부 | 권장 | 사람확인
    judge: str = "판단"  # 계산 | 판단 | 기재
    metric: str = ""  # 계산 규정일 때 checks.METRICS의 키
    op: str = ""  # >= | <= | ==
    value: Optional[float] = None
    source: str = ""


class GenerationInput(BaseModel):
    draft: DraftInfo = DraftInfo()
    outputs: List[str] = ["편성표"]  # 무엇을 만드는지: 편성표 | 단원 설계
    course: CourseInfo
    # 학습자
    target_learners: str = ""  # 훈련 대상
    non_major_ratio: Optional[float] = None  # 비전공자 비율(%)
    prior_experience: List[str] = Field(default=[], validation_alias=AliasChoices("prior_experience", "entry_knowledge"))
    learner_goal: str = ""  # 학습자 목표 (예: 게임 클라이언트 개발자 취업)
    # 교육 목적 = 생성의 가장 중요한 기준
    purpose: str = ""
    # 규정: 운영 규정 조항은 data/regulation_rules.json. 공고(announcement_path)는 있으면 참고, confirmed_rules는 CLI용 추가 규정
    confirmed_rules: List[ConfirmedRule] = []
    announcement_path: str = ""
    announcement_text: str = ""  # 실행할 때 announcement_path에서 읽어 채움
    # 편성 조건
    project_ratio: float = 0.3  # 전체 시간 중 프로젝트 시간 비율 하한
    required_subjects: List[str] = []  # 필수 교과목 (이름에 핵심 단어가 들어가면 인정)
    company_tasks: List[CompanyTask] = []
    # 기준·실행
    pass_score: float = 3.1  # 합격 기준(페르소나 평균 점수). 생성에는 쓰지 않고 검증 agent로 넘긴다
    budget_krw: float = 2000  # 1회 실행 예산 상한(원). 넘으면 멈추고 그때까지 결과를 저장
    # 수정 모드
    revision_request: str = ""  # 강사의 말로 하는 수정 요청
    revision_items: List[str] = []  # 강사가 고른 검증 보완점 (한 줄씩)
    revision_targets: List[str] = []  # 반드시 고쳐야 할 교과목 id (보완점 위치에서 찾음)
    persona_feedback: Optional[PersonaFeedback] = None
    previous_curriculum: Optional[Dict[str, Any]] = None
    previous_curriculum_path: str = ""

    @property
    def entry_knowledge(self) -> List[str]:  # 선수 개념 검사의 출발점
        return self.prior_experience

    @property
    def weeks(self) -> float:
        return round(self.course.months * 52 / 12, 1) if self.course.months else 0

    @property
    def revise_mode(self) -> bool:
        return self.previous_curriculum is not None

    @property
    def wants_units(self) -> bool:
        return "단원 설계" in self.outputs


# ---------- 작업 공간(출력) ----------

class Goal(BaseModel):
    id: str
    text: str


class Unit(BaseModel):
    title: str
    hours: float
    activities: List[str] = []
    deliverable: str = ""


class Subject(BaseModel):
    id: str = ""
    title: str
    category: str = "실습"  # 이론 | 실습 | 프로젝트
    theory_hours: float = 0
    practice_hours: float = 0
    project_hours: float = 0
    mode: str = "집체"
    goals: List[str] = []
    topics: List[str] = []
    concepts_taught: List[str] = []
    prerequisites: List[str] = []
    assessment: str = ""
    linked_goals: List[str] = []
    company_task_ids: List[str] = []
    rationale: str = ""
    units: List[Unit] = []

    @property
    def hours(self) -> float:
        return self.theory_hours + self.practice_hours + self.project_hours


class Project(BaseModel):
    id: str = ""
    title: str
    company_task_id: str = ""
    subject_ids: List[str] = []
    description: str = ""
    portfolio_output: str = ""


class SkillTarget(BaseModel):
    """숙련목표: 수료할 때 무엇을 어느 수준까지 할 수 있어야 하는지 (운영 규정의 '숙련목표')."""
    id: str = ""
    text: str
    level: str = ""  # 예: 안내를 받아 수행 | 독립 수행 | 응용
    subject_ids: List[str] = []


class QuizQuestion(BaseModel):
    question: str
    choices: List[str]  # 객관식 보기 4개
    answer: int  # 정답 보기 번호 (1~4)
    explanation: str = ""
    skill_target_ids: List[str] = []


class Quiz(BaseModel):
    """교과목 이해도 평가용 객관식 퀴즈. week가 없으면 교과목이 끝나는 주차에 본다."""
    id: str = ""
    subject_id: str
    week: Optional[int] = None
    questions: List[QuizQuestion] = []


class ProficiencyMethod(BaseModel):
    """숙련도를 높이는 방법 (보충학습 등)."""
    method: str
    description: str = ""
    timing: str = ""  # 언제 하는지 (예: 퀴즈 다음 날)
    subject_ids: List[str] = []


class Change(BaseModel):
    target: str
    action: str  # 추가 | 수정 | 삭제 | 이동
    reason: str
    source: str = ""  # 페르소나 피드백 / 점검 위반 / 설계


class Curriculum(BaseModel):
    meta: Dict[str, Any] = {}
    intent_summary: str = ""
    learning_goals: List[Goal] = []
    schedule: Dict[str, Any] = {}
    subjects: List[Subject] = []
    projects: List[Project] = []
    skill_targets: List[SkillTarget] = []
    quizzes: List[Quiz] = []
    proficiency_methods: List[ProficiencyMethod] = []
    compliance: List[Dict[str, Any]] = []  # 운영 규정 대조표 (조항별 지킴/위반/확인 필요)
    regulation_notes: List[Dict[str, str]] = []
    check_report: Dict[str, Any] = {}
    validation_criteria: Dict[str, Any] = {}  # 검증 agent로 넘기는 기준 (합격 기준 등)
    change_log: List[Change] = []
    open_items: List[str] = Field(default_factory=list)

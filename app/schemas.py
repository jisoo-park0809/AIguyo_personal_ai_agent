"""화면 <-> API <-> AI 사이에서 주고받는 데이터 형식.

나중에 agent 파이프라인을 붙일 때도 이 형식(특히 Curriculum, Validation)을
입출력 계약으로 유지하면 화면 코드는 바꿀 필요가 없다.
"""
import re
from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, Field, computed_field, field_validator


def _to_int(v: Any) -> Optional[int]:
    if v is None or isinstance(v, int):
        return v
    m = re.search(r"\d+", str(v))
    return int(m.group()) if m else None


def _to_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [s.strip(" -•\t") for s in v.splitlines() if s.strip()]
    return [str(x) for x in v]


class CompanyTask(BaseModel):
    company: str = ""
    title: str = ""


class Survey(BaseModel):
    """과정 정보 (팀 통합 입력 구성안). 규정 검색·학생 페르소나는 아래 기존 항목(target, level, funding, subject)을 쓴다."""
    # 기존 항목: 예전 저장본과 규정 검색·페르소나가 그대로 쓴다
    target: str = "전공+비전공"  # "전공" | "전공+비전공" (비전공자 비율로 정함)
    level: str = "일반"  # "심화" | "일반"
    funding: str = "KDT"  # = 사업 프로필
    subject: str = ""  # = 분야·직군
    duration: str = ""  # 기간·시간을 한 줄로 (예: 5개월(약 22주) · 800시간)
    # 교육 목적·설계 의도 (예전 저장본의 extra 키도 읽는다)
    intent: str = Field("", validation_alias=AliasChoices("intent", "extra"))
    # 기본 정보
    owner: str = ""  # 담당자
    # 과정 조건
    total_hours: Optional[int] = None
    daily_hours: Optional[int] = None
    days_per_week: Optional[int] = None
    months: Optional[float] = None  # 기간(개월)
    training_mode: str = ""  # 집체 | 원격 | 혼합
    # 학습자
    target_desc: str = ""  # 훈련 대상
    non_major_ratio: Optional[int] = None  # 비전공자 비율(%)
    prior_experience: str = ""  # 사전 경험
    learner_goal: str = ""  # 학습자 목표
    # 편성 조건
    project_ratio: Optional[int] = None  # 프로젝트 비율 하한(%)
    required_subjects: List[str] = []
    company_tasks: List[CompanyTask] = []
    # 기준·실행 (검증·실행 단계에서 쓰고 생성 프롬프트에는 넣지 않음)
    pass_score: Optional[float] = None  # 합격 기준(페르소나 평균 점수)
    budget_krw: Optional[int] = None  # 1회 예산 상한(원)


class DocPart(BaseModel):
    """신청 서류 묶음 안의 개별 문서 (공고문, 심사기준, 사업계획서 서식 등)."""
    id: str = ""
    name: str = ""
    kind: str = "other"  # announcement(공고·선정 방식) | criteria(심사 기준) | form(작성할 서류) | other(참고)
    summary: str = ""
    text: str = ""
    selected: bool = False  # form일 때 저장 시 작성할지 여부
    source_format: str = ""  # 이 문서가 들어 있던 파일 형식 (hwp, hwpx, docx, pdf …, 붙여넣기는 빈칸)

    @computed_field
    @property
    def output_format(self) -> str:
        """작성본 저장 형식: 원본 형식을 따른다. 한글은 .hwpx, 그 밖(PDF·텍스트 등)은 편집할 수 있는 .docx."""
        return "hwpx" if self.source_format in ("hwp", "hwpx") else "docx"


class DocContext(BaseModel):
    # 각종 신청 서류 및 공고안 (예전 저장본의 business_plan 키도 읽는다)
    application_docs: str = Field("", validation_alias=AliasChoices("application_docs", "business_plan"))
    criteria: str = ""
    documents: List[DocPart] = []


class RegSnippet(BaseModel):
    source: str
    page: int
    article: str = ""  # 예: "제19조(내일배움카드 훈련과정의 요건)"
    text: str


class Module(BaseModel):
    period: str = ""
    title: str = ""
    hours: Optional[int] = None
    objectives: List[str] = []
    topics: List[str] = []
    practice: str = ""
    prerequisites: List[str] = []
    rationale: str = ""  # 이 위치·시간으로 둔 이유 (생성 agent)

    _int = field_validator("hours", mode="before")(_to_int)
    _list = field_validator("objectives", "topics", "prerequisites", mode="before")(_to_list)


class Project(BaseModel):
    name: str = ""
    period: str = ""
    description: str = ""


class Curriculum(BaseModel):
    title: str = "커리큘럼"
    summary: str = ""
    target_summary: str = ""
    total_weeks: Optional[int] = None
    total_hours: Optional[int] = None
    learning_goals: List[str] = []
    modules: List[Module] = []
    projects: List[Project] = []
    assessment: str = ""
    compliance_notes: List[str] = []
    change_log: List[str] = []
    design_rationale: List[str] = []  # 왜 이렇게 짰는지: 교육 목적 해석, 시간 배분 이유
    # 버전: 같은 과정에서 생성·수정·검증 반영할 때마다 v1, v2, v3 …
    lineage_id: str = ""
    version: int = 0
    version_note: str = ""
    # 생성 agent 결과: 숙련목표, 객관식 퀴즈, 숙련도 향상 방법, 운영 규정 대조표
    skill_targets: List[Dict[str, Any]] = []
    quizzes: List[Dict[str, Any]] = []
    proficiency_methods: List[Dict[str, Any]] = []
    compliance_table: List[Dict[str, Any]] = []
    # 교과목별 학습 자료 (설명 → 실습, 퀴즈는 quizzes) — 미리보기에서 '학습 자료 만들기'로 만든다
    learning_materials: List[Dict[str, Any]] = []
    materials_meta: Dict[str, Any] = {}
    # 생성 agent가 만든 원본(교과목·개념 태그·주차). 수정·검증 agent가 정확하게 다시 쓰려고 함께 보관한다
    agent_curriculum: Optional[Dict[str, Any]] = None

    _int = field_validator("total_weeks", "total_hours", mode="before")(_to_int)
    _list = field_validator("learning_goals", "compliance_notes", "change_log", mode="before")(_to_list)


class Gap(BaseModel):
    id: str = ""
    persona: str = ""
    issue: str = ""
    location: str = ""
    severity: str = "중간"  # "높음" | "중간" | "낮음"
    suggestion: str = ""


class PersonaReview(BaseModel):
    persona: str = ""
    profile: str = ""
    score: Optional[int] = None
    strengths: List[str] = []
    gaps: List[Gap] = []

    _int = field_validator("score", mode="before")(_to_int)
    _list = field_validator("strengths", mode="before")(_to_list)


class Validation(BaseModel):
    overall: str = ""
    personas: List[PersonaReview] = []
    verdict: str = ""  # 합격 | 불합격 (학생 검증 agent)
    score: Optional[float] = None  # 가중 평균 점수
    quiz_fit: List[Dict[str, Any]] = []  # 교과목 퀴즈 난이도: 학생별 쉬움/적절/어려움


class FormBlock(BaseModel):
    type: str = "paragraph"  # heading | paragraph | bullet | table
    text: str = ""
    level: int = 1
    rows: List[List[str]] = []

    @field_validator("rows", mode="before")
    @classmethod
    def _rows(cls, v):
        return [[str(c) for c in row] for row in (v or []) if isinstance(row, list)]


class FilledForm(BaseModel):
    title: str = ""
    blocks: List[FormBlock] = []


# ---- 요청 바디 ----

class GenerateReq(BaseModel):
    context: DocContext
    survey: Survey


class ReviseReq(BaseModel):
    context: DocContext
    survey: Survey
    curriculum: Curriculum
    instruction: str


class ValidateReq(BaseModel):
    context: DocContext
    survey: Survey
    curriculum: Curriculum
    learner_ids: Optional[List[str]] = None  # 검증할 학습자 유형 id (없으면 기본 학생 4명)


class MaterialsReq(BaseModel):
    context: DocContext
    survey: Survey
    curriculum: Curriculum


class ApplyFeedbackReq(BaseModel):
    context: DocContext
    survey: Survey
    curriculum: Curriculum
    gaps: List[Gap]


class ParseReq(BaseModel):
    text: str


class AnalyzeReq(BaseModel):
    text: str


class FilledDoc(BaseModel):
    """미리보기에서 이미 작성한 서식 (id는 DocPart.id)."""
    id: str
    form: FilledForm


class FillFormsReq(BaseModel):
    context: DocContext
    survey: Survey
    curriculum: Curriculum
    ids: List[str]


class SaveReq(BaseModel):
    category: str
    context: DocContext
    survey: Survey
    curriculum: Curriculum
    validation: Optional[Validation] = None
    regulations: List[RegSnippet] = []
    # 미리보기에서 작성해 둔 서식은 다시 작성하지 않고 그대로 저장한다
    filled_forms: List[FilledDoc] = []

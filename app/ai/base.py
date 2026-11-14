"""AI 공급자 인터페이스.

화면과 API는 이 인터페이스만 호출한다. OpenAI 임시 구현, 모의(Mock) 구현,
그리고 나중에 붙일 자체 agent 파이프라인이 모두 이 클래스를 상속한다.

모든 메서드는 dict를 반환하며, 형식은 app/schemas.py의 Curriculum / Validation / FilledForm과 같다.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List

from ..documents import criteria_text
from ..schemas import DocPart, RegSnippet, Survey


@dataclass
class AIContext:
    application_docs: str  # 각종 신청 서류 및 공고안 원문
    criteria: str
    survey: Survey
    regulations: List[RegSnippet] = field(default_factory=list)
    documents: List[DocPart] = field(default_factory=list)  # 원문을 문서별로 나눈 결과

    @property
    def effective_criteria(self) -> str:
        return criteria_text(self.criteria, self.documents)


class InputError(Exception):
    """입력이 잘못돼 AI를 부르지 않은 경우 (화면에 400으로 이유를 보여 준다)."""


class CurriculumAI(ABC):
    name = "base"
    uses_learner_cards = False  # True면 검증에 학습자 유형 카드(validator_agent 형식)를 받는다

    @abstractmethod
    def generate(self, ctx: AIContext) -> Dict:
        """신청 서류·공고안·심사기준·운영규정·설문 조건으로 커리큘럼을 새로 만든다."""

    @abstractmethod
    def revise(self, ctx: AIContext, curriculum: Dict, instruction: str) -> Dict:
        """자연어 수정 요청을 반영한 커리큘럼을 돌려준다. change_log에 변경 사항을 남긴다."""

    @abstractmethod
    def validate(self, ctx: AIContext, curriculum: Dict, personas: List[Dict]) -> Dict:
        """학생 페르소나별로 커리큘럼을 검증한다.

        검증 쪽에는 생성 과정의 추론을 넘기지 않는다. 결과물(curriculum)과
        조건(ctx)만 보고 학생 입장에서 판단하게 한다.
        """

    @abstractmethod
    def apply_feedback(self, ctx: AIContext, curriculum: Dict, gaps: List[Dict]) -> Dict:
        """선택된 검증 피드백(gaps)을 반영한 커리큘럼을 돌려준다."""

    @abstractmethod
    def parse(self, text: str) -> Dict:
        """붙여넣거나 업로드한 커리큘럼 문서 텍스트를 Curriculum 형식으로 구조화한다."""

    @abstractmethod
    def analyze_documents(self, outline: List[Dict], text: str) -> Dict:
        """신청 서류 묶음에서 문서별 시작 줄을 찾는다.

        반환: {"parts": [{"name", "kind", "start_line", "summary"}]}
        kind = announcement | criteria | form | other
        """

    @abstractmethod
    def fill_form(self, ctx: AIContext, curriculum: Dict, form: Dict) -> Dict:
        """신청 서식(form: DocPart)을 커리큘럼과 조건으로 채운다. 반환 형식은 FilledForm."""

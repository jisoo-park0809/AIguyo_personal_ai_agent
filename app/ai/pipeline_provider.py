"""자체 agent 파이프라인 연결 자리.

.env에서 AI_PROVIDER=pipeline 으로 바꾸면 이 클래스가 사용된다.

  generate        -> 생성 agent (generator_agent/): tool 사용 + 코드 점검 + 자동 수정
  revise          -> 생성 agent 수정 모드 (말로 하는 수정 요청)
  apply_feedback  -> 생성 agent 수정 모드 (강사가 고른 검증 보완점, 해당 교과목은 반드시 고침)
  validate        -> 학생 검증 agent (validator_agent/): 학생 페르소나 4명이 수강해 보고 코드가 판정
  parse, analyze_documents, fill_form -> OpenAI 1회 호출 (서식 작성 agent 연결 예정)

OPENAI_API_KEY가 없으면 생성 agent는 시연용 정책으로, 나머지는 모의 응답으로 동작한다.
"""
import os
from typing import Dict, List

from .base import AIContext, CurriculumAI, InputError


class PipelineProvider(CurriculumAI):
    uses_learner_cards = True

    def __init__(self):
        self.has_key = bool(os.getenv("OPENAI_API_KEY"))
        if self.has_key:
            from .openai_provider import OpenAIProvider
            self.fallback = OpenAIProvider()
        else:
            from .mock_provider import MockProvider
            self.fallback = MockProvider()
        model = os.getenv("GENERATOR_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
        self.name = f"pipeline (생성 agent: {model if self.has_key else '시연 정책'})"

    def _run_generator(self, inp, ctx: AIContext) -> Dict:
        from generator_agent.agent import GeneratorAgent

        from .agent_bridge import to_app_curriculum

        out = GeneratorAgent(inp, provider="openai" if self.has_key else "mock").run()
        if out.get("rejected"):
            raise InputError("입력을 확인해 주세요: " + " / ".join(out["rejected"]))
        return to_app_curriculum(out["curriculum"], ctx)

    def generate(self, ctx: AIContext) -> Dict:
        from .agent_bridge import to_generation_input

        return self._run_generator(to_generation_input(ctx), ctx)

    def revise(self, ctx: AIContext, curriculum: Dict, instruction: str) -> Dict:
        from .agent_bridge import revision_input

        return self._run_generator(revision_input(ctx, curriculum, request=instruction), ctx)

    def validate(self, ctx: AIContext, curriculum: Dict, personas: List[Dict]) -> Dict:
        # personas: 학습자 유형 카드 (기본 학생 1~4 + 운영자가 추가한 유형 중 고른 것, app/learner_types.py)
        from validator_agent.agent import StudentValidator
        from validator_agent.schemas import ValidationInput
        from validator_agent.views import from_app

        s = ctx.survey
        notes = curriculum.get("compliance_notes", [])
        rules_pass = (True if any("[코드 점검 통과]" in n for n in notes)
                      else False if any("[코드 점검 미통과]" in n for n in notes) else None)
        from validator_agent.views import from_generator

        from .agent_bridge import request_for_validator

        # 생성 agent 원본이 있으면 개념 태그까지 쓰고, 없으면 앱 모듈에서 학생용 보기를 만든다
        agent_cur = curriculum.get("agent_curriculum")
        view = from_generator(agent_cur, request_for_validator(ctx)) if agent_cur else from_app(curriculum, s)
        from validator_agent.schemas import PersonaCard

        cards = [PersonaCard.model_validate(p) for p in personas] if personas else []
        inp = ValidationInput(view=view, non_major_ratio=s.non_major_ratio,
                              pass_score=s.pass_score if s.pass_score is not None else 3.1,
                              budget_krw=s.budget_krw if s.budget_krw is not None else 2000, rules_pass=rules_pass,
                              personas=cards)
        result = StudentValidator(inp, provider="openai" if self.has_key else "mock").run()
        return result["app_validation"]

    def apply_feedback(self, ctx: AIContext, curriculum: Dict, gaps: List[Dict]) -> Dict:
        from .agent_bridge import revision_input

        return self._run_generator(revision_input(ctx, curriculum, gaps=gaps), ctx)

    def parse(self, text: str) -> Dict:
        return self.fallback.parse(text)

    def analyze_documents(self, outline: List[Dict], text: str) -> Dict:
        return self.fallback.analyze_documents(outline, text)

    def fill_form(self, ctx: AIContext, curriculum: Dict, form: Dict) -> Dict:
        return self.fallback.fill_form(ctx, curriculum, form)

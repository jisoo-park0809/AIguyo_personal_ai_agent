"""임시 AI: OpenAI API. 자체 agent 파이프라인이 준비되면 pipeline_provider로 교체한다."""
import json
import os
from typing import Dict, List

from ..documents import heuristic_parts
from . import prompts
from .base import AIContext, CurriculumAI


class OpenAIProvider(CurriculumAI):
    def __init__(self):
        from openai import OpenAI

        self.client = OpenAI(timeout=float(os.getenv("OPENAI_TIMEOUT", "120")), max_retries=2)  # OPENAI_API_KEY 환경변수 사용
        self.model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
        self.name = f"openai ({self.model})"

    def _json(self, system: str, user: str) -> Dict:
        resp = self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return json.loads(resp.choices[0].message.content or "{}")

    def generate(self, ctx: AIContext) -> Dict:
        return self._json(prompts.GENERATE_SYSTEM, prompts.generate_user(ctx))

    def revise(self, ctx: AIContext, curriculum: Dict, instruction: str) -> Dict:
        return self._json(prompts.REVISE_SYSTEM, prompts.revise_user(ctx, curriculum, instruction))

    def validate(self, ctx: AIContext, curriculum: Dict, personas: List[Dict]) -> Dict:
        return self._json(prompts.VALIDATE_SYSTEM, prompts.validate_user(ctx, curriculum, personas))

    def apply_feedback(self, ctx: AIContext, curriculum: Dict, gaps: List[Dict]) -> Dict:
        return self._json(prompts.APPLY_SYSTEM, prompts.apply_user(ctx, curriculum, gaps))

    def parse(self, text: str) -> Dict:
        return self._json(prompts.PARSE_SYSTEM, prompts._clip(text))

    def analyze_documents(self, outline: List[Dict], text: str) -> Dict:
        result = self._json(prompts.ANALYZE_SYSTEM, prompts.analyze_user(outline))
        # AI가 나누지 못하면 규칙 기반 분할로 대신한다
        return result if result.get("parts") else {"parts": heuristic_parts(text)}

    def fill_form(self, ctx: AIContext, curriculum: Dict, form: Dict) -> Dict:
        return self._json(prompts.FILL_SYSTEM, prompts.fill_user(ctx, curriculum, form))

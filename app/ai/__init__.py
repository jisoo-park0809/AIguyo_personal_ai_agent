import os
from functools import lru_cache

from .base import AIContext, CurriculumAI

__all__ = ["AIContext", "CurriculumAI", "get_provider"]


@lru_cache(maxsize=1)
def get_provider() -> CurriculumAI:
    """AI_PROVIDER = openai | mock | pipeline. 미지정 시 API 키가 있으면 openai, 없으면 mock."""
    choice = os.getenv("AI_PROVIDER", "").lower() or ("openai" if os.getenv("OPENAI_API_KEY") else "mock")
    if choice == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider()
    if choice == "pipeline":
        from .pipeline_provider import PipelineProvider
        return PipelineProvider()
    from .mock_provider import MockProvider
    return MockProvider()

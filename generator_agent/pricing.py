"""AI 호출 비용 계산 (예산 상한 판단용).

단가는 설정값입니다. 실제 단가는 공급자 요금표로 확인하고, 바뀌면 PRICES_USD나 환경변수를 고치세요.
"""
import os

# 모델별 100만 토큰당 달러 (입력, 출력, 캐시된 입력). gpt-5.4-mini는 공식 모델 페이지 기준 (2026-11-09 확인)
PRICES_USD = {
    "gpt-4o-mini": (0.15, 0.60, 0.075),
    "gpt-4o": (2.50, 10.00, 1.25),
    "gpt-4.1-mini": (0.40, 1.60, 0.10),
    "gpt-4.1": (2.00, 8.00, 0.50),
    "gpt-5-nano": (0.05, 0.40, 0.005),
    "gpt-5-mini": (0.25, 2.00, 0.025),
    "gpt-5": (1.25, 10.00, 0.125),
    "gpt-5.4-mini": (0.75, 4.50, 0.075),
}
KRW_PER_USD = float(os.getenv("KRW_PER_USD", "1400"))


def price_of(model: str):
    if os.getenv("GENERATOR_PRICE_IN_USD") and os.getenv("GENERATOR_PRICE_OUT_USD"):
        p_in = float(os.environ["GENERATOR_PRICE_IN_USD"])
        return p_in, float(os.environ["GENERATOR_PRICE_OUT_USD"]), float(os.getenv("GENERATOR_PRICE_CACHED_USD", p_in))
    for name, price in PRICES_USD.items():  # 정확한 이름이거나 날짜 버전(gpt-4.1-2025-04-14)일 때만
        if model == name or model.startswith(name + "-20"):
            return price
    return PRICES_USD["gpt-4o"]  # 모르는 모델은 비싼 쪽으로 잡아 예산을 넘기지 않게 한다


def cost_krw(model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    p_in, p_out, p_cached = price_of(model)
    fresh = max(input_tokens - cached_tokens, 0)
    return (fresh * p_in + cached_tokens * p_cached + output_tokens * p_out) / 1_000_000 * KRW_PER_USD

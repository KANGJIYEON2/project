"""LLM 모델별 단가 테이블 (USD per token).

값은 2026년 기준 공개 가격을 사용. 모델 추가/단가 변경 시 여기서만 수정.
미등록 모델은 0으로 계산하고 경고 로그.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 1 토큰당 USD. (1M tokens 당 USD / 1_000_000)
PRICING: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {
        "input": 0.150 / 1_000_000,
        "output": 0.600 / 1_000_000,
    },
    "gpt-4o": {
        "input": 2.50 / 1_000_000,
        "output": 10.00 / 1_000_000,
    },
    "claude-haiku-4-5": {
        "input": 1.00 / 1_000_000,
        "output": 5.00 / 1_000_000,
    },
    "claude-sonnet-4-6": {
        "input": 3.00 / 1_000_000,
        "output": 15.00 / 1_000_000,
    },
}


def compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """모델 키 매칭으로 비용 산정 (USD).

    예) "gpt-4o-mini-test" 같은 변형 모델명도 prefix 매칭으로 처리.
    """
    rates = PRICING.get(model)
    if rates is None:
        # prefix 매칭 (예: 테스트용 "gpt-4o-mini-test")
        for key, value in PRICING.items():
            if model.startswith(key):
                rates = value
                break
    if rates is None:
        logger.warning("pricing.unknown_model", extra={"model": model})
        return 0.0
    return round(
        prompt_tokens * rates["input"] + completion_tokens * rates["output"],
        8,
    )

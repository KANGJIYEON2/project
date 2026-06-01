"""OpenAI 구조화 출력 클라이언트.

`TriageLLMOutput` Pydantic 스키마를 그대로 response_format으로 넘겨
LLM 자유 텍스트 파싱을 차단한다.

호출자에게는 (분류 결과, 토큰/모델 메트릭) 튜플을 반환한다.
메트릭은 services/triage.py 에서 LLMUsage 로 영속화된다.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.config import get_settings
from app.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from app.schemas.triage import TriageLLMOutput

logger = logging.getLogger(__name__)


@dataclass
class LLMCallMetrics:
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


_settings = get_settings()
_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not _settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
        _client = AsyncOpenAI(api_key=_settings.openai_api_key)
    return _client


async def classify_review(
    content: str,
    rating: int | None,
    source: str,
    model: str | None = None,
) -> tuple[TriageLLMOutput, LLMCallMetrics]:
    """리뷰 본문을 분류하여 (분류 결과, 호출 메트릭) 반환.

    model 이 None 이면 config 기본값(openai_model) 사용.
    "claude-" 로 시작하면 Anthropic API 로 라우팅.
    """
    model = model or _settings.openai_model

    # LLM Rate Limit 체크
    from app.errors import RateLimitExceeded
    from app.services.rate_limiter import llm_limiter

    llm_limit = _settings.llm_rate_limit_per_minute
    if llm_limit > 0:
        result = llm_limiter.check("global", llm_limit, 60)
        if not result.allowed:
            raise RateLimitExceeded(result.retry_after or 1.0)

    if model.startswith("claude-"):
        from app.llm.anthropic_client import classify_review_anthropic
        return await classify_review_anthropic(model, content, rating, source)

    client = get_client()

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(content, rating, source)},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )

    usage = response.usage
    metrics = LLMCallMetrics(
        model=model,
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        total_tokens=usage.total_tokens if usage else 0,
    )
    logger.info(
        "llm.classify",
        extra={
            "model": metrics.model,
            "prompt_tokens": metrics.prompt_tokens,
            "completion_tokens": metrics.completion_tokens,
        },
    )

    raw = response.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
        return TriageLLMOutput.model_validate(data), metrics
    except (json.JSONDecodeError, ValidationError) as e:
        logger.error("llm.parse_failed", extra={"raw": raw[:500]})
        raise ValueError(f"LLM 응답을 파싱할 수 없습니다: {e}") from e

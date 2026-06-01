"""Anthropic Claude 구조화 출력 클라이언트.

OpenAI 클라이언트와 동일한 인터페이스로 Claude 모델을 호출한다.
tool_use 패턴으로 구조화 JSON 출력을 강제한다.
"""
from __future__ import annotations

import logging

from anthropic import AsyncAnthropic

from app.config import get_settings
from app.llm.client import LLMCallMetrics
from app.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from app.schemas.triage import TriageLLMOutput

logger = logging.getLogger(__name__)

_anthropic_client: AsyncAnthropic | None = None

# TriageLLMOutput 을 Anthropic tool 스키마로 변환
_TRIAGE_TOOL = {
    "name": "classify_review",
    "description": "리뷰 분류 결과를 반환합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["medical_complaint", "facility_complaint", "staff_complaint", "wait_time", "improvement", "praise", "inquiry", "other"],
            },
            "severity": {
                "type": "string",
                "enum": ["P0", "P1", "P2", "P3"],
            },
            "sentiment_score": {
                "type": "number",
                "minimum": -1.0,
                "maximum": 1.0,
            },
            "assigned_team": {
                "type": "string",
                "enum": ["medical", "nursing", "admin", "facility"],
            },
            "summary": {
                "type": "string",
                "maxLength": 200,
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
            },
        },
        "required": [
            "category", "severity", "sentiment_score",
            "assigned_team", "summary", "tags", "confidence",
        ],
    },
}


def _get_anthropic_client() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")
        _anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


async def classify_review_anthropic(
    model: str,
    content: str,
    rating: int | None,
    source: str,
) -> tuple[TriageLLMOutput, LLMCallMetrics]:
    """Claude 모델로 리뷰를 분류."""
    client = _get_anthropic_client()
    user_prompt = build_user_prompt(content, rating, source)

    response = await client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[_TRIAGE_TOOL],
        tool_choice={"type": "tool", "name": "classify_review"},
    )

    usage = response.usage
    metrics = LLMCallMetrics(
        model=model,
        prompt_tokens=usage.input_tokens,
        completion_tokens=usage.output_tokens,
        total_tokens=usage.input_tokens + usage.output_tokens,
    )
    logger.info(
        "llm.classify.anthropic",
        extra={
            "model": model,
            "prompt_tokens": metrics.prompt_tokens,
            "completion_tokens": metrics.completion_tokens,
        },
    )

    # tool_use 블록에서 input 추출
    tool_input = None
    for block in response.content:
        if block.type == "tool_use" and block.name == "classify_review":
            tool_input = block.input
            break

    if tool_input is None:
        raise ValueError("Claude 응답에서 tool_use 블록을 찾을 수 없습니다.")

    return TriageLLMOutput.model_validate(tool_input), metrics

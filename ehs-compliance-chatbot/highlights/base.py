"""Base AI Agent — 모든 에이전트의 공통 기반"""

from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from app.config import Settings


class BaseAgent:
    """각 AI Agent의 기반 클래스. 전문화된 시스템 프롬프트와 출력 스키마를 가진다."""

    name: str = "base"
    system_prompt: str = "You are a helpful assistant."
    model: str = "gpt-4o-mini"
    temperature: float = 0.3

    def __init__(self) -> None:
        self._client: OpenAI | None = None

    def initialize(self, settings: Settings) -> None:
        if settings.OPENAI_API_KEY:
            self._client = OpenAI(
                api_key=settings.OPENAI_API_KEY,
                timeout=settings.OPENAI_TIMEOUT,
            )

    @property
    def is_ready(self) -> bool:
        return self._client is not None

    def _chat(self, user_prompt: str, system_override: str | None = None) -> str:
        """GPT 호출 → 텍스트 응답"""
        if not self._client:
            raise RuntimeError(f"{self.name} agent: OpenAI client not initialized")

        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_override or self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.temperature,
        )
        return resp.choices[0].message.content.strip()

    def _chat_json(self, user_prompt: str, system_override: str | None = None) -> Any:
        """GPT 호출 → JSON 파싱"""
        raw = self._chat(user_prompt, system_override)
        # ```json ... ``` 래핑 제거
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(raw)

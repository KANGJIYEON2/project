"""사고 분석 Agent — 사고 등록 시 원인 분석 + 예방 체크리스트 자동 생성"""

from __future__ import annotations

from typing import Any

from app.services.ai_agents.base import BaseAgent


class IncidentAgent(BaseAgent):
    name = "incident_agent"
    system_prompt = (
        "당신은 대한민국 산업안전 전문가다. "
        "사고 정보를 분석하여 원인 분석, 예방 체크리스트, 재발 방지 대책을 JSON으로 제공한다. "
        "반드시 한국어로 답하고, 현장에서 바로 적용 가능한 구체적 조치를 제시하라."
    )
    temperature = 0.2

    def analyze_incident(
        self,
        incident_type: str,
        severity: str,
        description: str,
        cause_estimate: str | None = None,
        location_info: str | None = None,
    ) -> dict[str, Any]:
        """사고 정보 → AI 분석 결과"""
        if not self.is_ready:
            return {"error": "AI agent not initialized"}

        prompt = f"""다음 산업재해 사고를 분석하라.

사고 유형: {incident_type}
심각도: {severity}
사고 설명: {description}
{f'추정 원인: {cause_estimate}' if cause_estimate else ''}
{f'발생 위치: {location_info}' if location_info else ''}

다음 JSON 형식으로 반환:
{{
  "root_cause_analysis": "근본 원인 분석 (2-3문장)",
  "contributing_factors": ["기여 요인 1", "기여 요인 2", ...],
  "prevention_checklist": [
    {{"item": "조치 항목", "priority": "high|medium|low", "category": "장비|교육|관리|환경"}},
    ...
  ],
  "recurrence_prevention": "재발 방지 대책 (2-3문장)",
  "related_regulations": ["관련 법령/규정 1", "관련 법령/규정 2"],
  "risk_level": "high|medium|low",
  "immediate_actions": ["즉시 조치 사항 1", "즉시 조치 사항 2"]
}}

JSON만 반환. 마크다운 없이."""

        try:
            return self._chat_json(prompt)
        except Exception as e:
            return {"error": str(e)}

    def generate_checklist(
        self,
        incident_type: str,
        description: str,
    ) -> list[dict[str, str]]:
        """사고 유형 기반 예방 체크리스트 생성"""
        if not self.is_ready:
            return []

        prompt = f"""다음 사고에 대한 예방 체크리스트를 생성하라.

사고 유형: {incident_type}
사고 내용: {description}

JSON 배열 형식으로 5-8개 항목 반환:
[
  {{"item": "점검 항목", "priority": "high|medium|low", "category": "장비|교육|관리|환경"}},
  ...
]

JSON만 반환."""

        try:
            return self._chat_json(prompt)
        except Exception:
            return []

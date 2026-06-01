import json
import os
from typing import List

from openai import OpenAI
from openai.types.chat import (
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)

from src.log.models import Log


class GPTAnalyzer:
    """
    GPT 기반 분석 보조 엔진.

    - RuleEngine 결과를 기준선(baseline)으로 사용 (룰 판정을 뒤집지 않음).
    - JSON 모드로 **구조화된 보고서**를 생성한다:
        summary  : 간결한 머리말 (2~3문장)
        sections : 보고서 본문 [{title, body}] — 상세/자세한 설명
        suspected_causes / recommended_actions : 간결한 항목 리스트
    """

    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key) if api_key else None

    def is_enabled(self) -> bool:
        return self.client is not None

    def analyze(
        self,
        *,
        logs: List[Log],
        rule_summary: str,
        rule_causes: List[str],
        rule_actions: List[str],
    ) -> dict:
        # GPT 비활성 → rule 결과 그대로 반환 (보고서 섹션 없음)
        if not self.is_enabled():
            return {
                "summary": rule_summary,
                "sections": [],
                "suspected_causes": rule_causes,
                "recommended_actions": rule_actions,
                "confidence_bonus": 0.0,
            }

        log_block = "\n".join(
            f"[{log.level}] {log.source}: {log.message}" for log in logs
        )

        system: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": (
                "You are a Site Reliability Engineer (SRE) writing an incident "
                "diagnostics report. The rule-engine analysis is the authoritative "
                "baseline — do NOT contradict it without clear justification; only "
                "deepen and explain it.\n"
                "Respond in KOREAN. Respond with a SINGLE JSON object only, no prose "
                "outside JSON, matching exactly this schema:\n"
                "{\n"
                '  "summary": "2~3문장 핵심 요약 (머리말)",\n'
                '  "sections": [\n'
                '    {"title": "현상 요약", "body": "..."},\n'
                '    {"title": "근본 원인 분석", "body": "..."},\n'
                '    {"title": "영향 범위", "body": "..."},\n'
                '    {"title": "진단 근거", "body": "..."},\n'
                '    {"title": "다음 단계", "body": "..."}\n'
                "  ],\n"
                '  "suspected_causes": ["간결한 원인 1", "..."],\n'
                '  "recommended_actions": ["간결한 조치 1", "..."],\n'
                '  "confidence_bonus": 0.05\n'
                "}\n"
                "Rules for the body text: each section body is 2~5 full sentences, "
                "specific and technical (cite log sources/levels and the matched "
                "rules where relevant). Use plain prose — NO markdown headings, NO "
                "bullet characters inside body. Provide 3~5 sections. "
                "confidence_bonus is a float in [0, 0.1]."
            ),
        }

        user: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": f"""
[Rule Engine Summary]
{rule_summary}

[Rule Engine Suspected Causes]
- {"; ".join(rule_causes)}

[Rule Engine Recommended Actions]
- {"; ".join(rule_actions)}

[Raw Logs]
{log_block}
""".strip(),
        }

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[system, user],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            data = json.loads(response.choices[0].message.content or "{}")
        except Exception:
            # 어떤 이유로든 GPT/파싱 실패 시 룰 결과로 안전 폴백
            return {
                "summary": rule_summary,
                "sections": [],
                "suspected_causes": rule_causes,
                "recommended_actions": rule_actions,
                "confidence_bonus": 0.0,
            }

        # --- 정규화 / 방어 ---
        sections = []
        for s in data.get("sections", []) or []:
            title = str(s.get("title", "")).strip()
            body = str(s.get("body", "")).strip()
            if title and body:
                sections.append({"title": title, "body": body})

        def _clean_list(values) -> List[str]:
            return [str(v).strip() for v in (values or []) if str(v).strip()]

        gpt_causes = _clean_list(data.get("suspected_causes"))
        gpt_actions = _clean_list(data.get("recommended_actions"))

        try:
            bonus = float(data.get("confidence_bonus", 0.05))
        except (TypeError, ValueError):
            bonus = 0.05
        bonus = max(0.0, min(bonus, 0.1))

        return {
            "summary": str(data.get("summary") or rule_summary).strip(),
            "sections": sections,
            "suspected_causes": gpt_causes or rule_causes,
            "recommended_actions": gpt_actions or rule_actions,
            "confidence_bonus": bonus,
        }

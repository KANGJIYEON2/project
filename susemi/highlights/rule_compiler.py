"""
법령 텍스트 → LLM → Rule JSON 컴파일러.

== 흐름 ==
1) 법령 본문 + 타깃 메타(rule_id/title/anchor) 입력
2) LLM 에 system + user 프롬프트로 요청 (출력은 Rule JSON 의 evaluator 부분만)
3) 응답을 Pydantic Rule 로 검증
4) 자동 검증 — 알려진 필드만 참조하는지 확인
5) RuleDraft 반환 (저장은 호출자 책임)

== 안전장치 ==
- evaluator 의 모든 field 참조가 EVAL_CONTEXT_FIELDS 에 있는지 검사
- 미상 필드 참조 시 confidence 디스카운트 + warning 누적
- LLM 응답 JSON 파싱 실패 시 1회 재시도
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from openai import AsyncOpenAI

from app.schemas.rule_draft_schema import RuleDraft
from app.schemas.rule_schema import (
    AllOfFlagsEvaluator,
    FieldRef,
    RatioOfField,
    Rule,
    SumOfFields,
    ThresholdEvaluator,
)
from app.services.rules_engine import EVAL_CONTEXT_FIELDS


_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


# 테스트에서 monkeypatch 할 수 있도록 간접 호출 래퍼
async def _call_llm(system: str, user: str, model: str = "gpt-4o-mini") -> str:
    resp = await _get_client().chat.completions.create(
        model=model,
        temperature=0.1,
        max_tokens=1500,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content or ""


# -------------------- 프롬프트 --------------------


SYSTEM_PROMPT = """\
당신은 한국 세법 룰 컴파일러입니다.
법령 본문을 읽고 시스템이 정의한 Rule JSON 스키마에 정확히 맞는 JSON 만 출력합니다.
스키마 외 임의 필드/구조 추가 금지. 설명 텍스트도 절대 출력하지 마세요.

evaluator 종류는 두 가지뿐입니다:
1) "threshold": 사용자 값과 기준값을 비교 (gt/gte/lt/lte/eq)
2) "all_of_flags": 여러 boolean 플래그가 모두 True 인지

법령에서 다음 형태가 보이면:
- "총급여의 25% 초과 사용분" → kind=threshold, threshold=ratio_of_field
- "본인이 세대주이면서 무주택이고…" → kind=all_of_flags

threshold 와 value 를 구성할 때 반드시 시스템이 제공한 필드만 사용하세요.
"""


def _format_field_list() -> str:
    lines = []
    for name, label in EVAL_CONTEXT_FIELDS.items():
        lines.append(f"- {name} : {label}")
    return "\n".join(lines)


def build_compile_prompt(
    *,
    law_text: str,
    target_rule_id: str,
    target_title: str,
    target_anchor: str,
    target_year: int,
    legal_text_hash: str | None,
    source_api_id: str | None,
) -> str:
    field_list = _format_field_list()
    return f"""\
다음 법령 본문에서 룰을 추출해 Rule JSON 으로 컴파일하세요.

== 타깃 메타 (이 값들을 그대로 결과에 포함) ==
rule_id: {target_rule_id}
title: {target_title}
year: {target_year}
legal_anchor: {target_anchor}
legal_text_hash: {legal_text_hash if legal_text_hash else 'null'}
source_api_id: {source_api_id if source_api_id else 'null'}

== 사용 가능한 필드 (이외의 이름 사용 금지) ==
{field_list}

== 법령 본문 ==
{law_text}

== 출력 (JSON 만) ==
{{
  "rule_id": "{target_rule_id}",
  "title": "{target_title}",
  "year": {target_year},
  "legal_anchor": "{target_anchor}",
  "legal_text_hash": {json.dumps(legal_text_hash)},
  "source_api_id": {json.dumps(source_api_id)},
  "human_reviewed": false,
  "confidence": 1.0,
  "compiled_at": "ISO timestamp",
  "compiled_by": "llm:gpt-4o-mini",
  "evaluator": {{
    "kind": "threshold | all_of_flags",
    ... (kind 에 맞는 필드)
  }}
}}

threshold 예시:
"evaluator": {{
  "kind": "threshold",
  "threshold": {{ "type": "ratio_of_field", "field": "total_salary", "ratio": 0.25 }},
  "value": {{ "type": "sum_of_fields", "fields": ["credit_card", "debit_card", "cash_receipt"] }},
  "comparison": "gte",
  "outputs": {{
    "threshold_key": "card_threshold_25",
    "value_key": "card_total_usage",
    "result_key": "card_meets_threshold"
  }}
}}

all_of_flags 예시:
"evaluator": {{
  "kind": "all_of_flags",
  "flags": ["householder", "no_house", "lease_contract"],
  "outputs": {{ "result_key": "rent_conditions_met" }}
}}
"""


# -------------------- 응답 파싱 / 검증 --------------------


_JSON_CLEANUP_PATTERNS = [
    (re.compile(r",\s*}"), "}"),
    (re.compile(r",\s*\]"), "]"),
]


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"JSON 시작/끝을 찾지 못했습니다: {text[:200]}…")
    s = text[start : end + 1]
    for pat, repl in _JSON_CLEANUP_PATTERNS:
        s = pat.sub(repl, s)
    return s


def _parse_rule_json(content: str) -> Rule:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = json.loads(_extract_json(content))
    return Rule.model_validate(data)


def _collect_field_refs(rule: Rule) -> list[str]:
    """rule.evaluator 안에서 참조된 모든 필드 이름을 수집."""
    refs: list[str] = []
    ev = rule.evaluator
    if isinstance(ev, ThresholdEvaluator):
        for expr in (ev.threshold, ev.value):
            if isinstance(expr, FieldRef):
                refs.append(expr.name)
            elif isinstance(expr, RatioOfField):
                refs.append(expr.field)
            elif isinstance(expr, SumOfFields):
                refs.extend(expr.fields)
    elif isinstance(ev, AllOfFlagsEvaluator):
        refs.extend(ev.flags)
    return refs


def _validate_rule(rule: Rule) -> tuple[float, list[str]]:
    """
    자동 검증 — confidence 와 경고 리스트 반환.
    - 1.0: 모든 참조 필드가 화이트리스트에 있음
    - 0.5: 일부 미상 필드 (warning 누적)
    - 0.0: 치명적 (Pydantic 단계에서 이미 잡힘 → 여기 도달 안 함)
    """
    warnings: list[str] = []
    confidence = 1.0

    refs = _collect_field_refs(rule)
    unknown = [r for r in refs if r not in EVAL_CONTEXT_FIELDS]
    if unknown:
        warnings.append(
            f"알 수 없는 필드 참조: {', '.join(unknown)} "
            f"— EVAL_CONTEXT_FIELDS 갱신 필요"
        )
        confidence = max(0.3, confidence - 0.2 * len(unknown))

    if rule.confidence > confidence:
        # LLM 자체 평가가 더 후하더라도 자동 검증 결과를 우선
        warnings.append(
            f"LLM self-confidence({rule.confidence}) > 자동 검증({confidence:.2f}) — 후자 채택"
        )

    return confidence, warnings


# -------------------- 공개 API --------------------


async def compile_rule(
    *,
    law_text: str,
    target_rule_id: str,
    target_title: str,
    target_anchor: str,
    target_year: int = 2025,
    legal_text_hash: str | None = None,
    source_api_id: str | None = None,
    source_chunk_id: str | None = None,
    parent_rule_id: str | None = None,
    llm_call: Callable[[str, str], Awaitable[str]] | None = None,
) -> RuleDraft:
    """
    법령 본문 → 컴파일된 RuleDraft.
    llm_call 인자로 LLM 호출을 주입 가능 (테스트용).
    """
    call = llm_call or _call_llm

    user_prompt = build_compile_prompt(
        law_text=law_text,
        target_rule_id=target_rule_id,
        target_title=target_title,
        target_anchor=target_anchor,
        target_year=target_year,
        legal_text_hash=legal_text_hash,
        source_api_id=source_api_id,
    )

    # 1차 + 1회 재시도
    raw = await call(SYSTEM_PROMPT, user_prompt)
    try:
        rule = _parse_rule_json(raw)
    except (ValueError, json.JSONDecodeError, Exception):
        raw = await call(
            SYSTEM_PROMPT,
            user_prompt + "\n\n방금 출력이 JSON 으로 파싱되지 않았습니다. 순수 JSON 만 다시 출력하세요.",
        )
        rule = _parse_rule_json(raw)

    # 코드가 강제하는 메타 — LLM 이 임의 변경 못 하게 덮어씀
    rule.rule_id = target_rule_id
    rule.title = target_title
    rule.year = target_year
    rule.legal_anchor = target_anchor
    rule.legal_text_hash = legal_text_hash
    rule.source_api_id = source_api_id
    rule.compiled_by = "llm:gpt-4o-mini"
    rule.compiled_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rule.human_reviewed = False

    confidence, warnings = _validate_rule(rule)
    rule.confidence = confidence

    excerpt = law_text.strip()
    if len(excerpt) > 1000:
        excerpt = excerpt[:1000] + "…"

    return RuleDraft(
        rule=rule,
        status="draft",
        source_law_excerpt=excerpt,
        source_chunk_id=source_chunk_id,
        parent_rule_id=parent_rule_id,
        validation_warnings=warnings,
    )


# 검증/Helper 함수 노출 (테스트용)
__all__ = [
    "compile_rule",
    "build_compile_prompt",
    "_collect_field_refs",
    "_validate_rule",
    "_parse_rule_json",
    "_call_llm",
    "SYSTEM_PROMPT",
]

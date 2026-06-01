"""
룰 정의 + 평가 결과 스키마.

== 룰 ==
- Rule: 외부 JSON 1건. legal_anchor 필수, evaluator 는 종류별 discriminated union.
- ValueExpr: threshold·value 로 쓰일 수 있는 수치 표현 (필드 참조/비율/필드 합/상수).
- Evaluator: 룰 평가 방식 (현재 'threshold' / 'all_of_flags' 두 종류; 추후 확장).

== 평가 결과 ==
- RuleEvaluation: 룰 1건 평가 결과. computed dict 와 result, legal_anchor 보유.

== 안전성 ==
- eval() / 동적 코드 실행 안 함. evaluator 는 모두 구조화된 데이터.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field


# ---------------- Value 표현 ----------------


class FieldRef(BaseModel):
    """평가 컨텍스트의 단일 필드 값."""

    type: Literal["field"] = "field"
    name: str


class RatioOfField(BaseModel):
    """필드 값 × 비율 (예: total_salary × 0.25)."""

    type: Literal["ratio_of_field"] = "ratio_of_field"
    field: str
    ratio: float


class SumOfFields(BaseModel):
    """여러 필드의 합 (예: credit_card + debit_card + cash_receipt)."""

    type: Literal["sum_of_fields"] = "sum_of_fields"
    fields: list[str]


class Constant(BaseModel):
    """상수."""

    type: Literal["constant"] = "constant"
    value: int


ValueExpr = Annotated[
    Union[FieldRef, RatioOfField, SumOfFields, Constant],
    Field(discriminator="type"),
]


# ---------------- 평가 방식 ----------------


class ThresholdOutputs(BaseModel):
    threshold_key: str
    value_key: str
    result_key: str


class ThresholdEvaluator(BaseModel):
    """
    threshold(기준값) vs value(사용자 값) 비교.
    예: card_total_usage >= total_salary * 0.25
    """

    kind: Literal["threshold"] = "threshold"
    threshold: ValueExpr
    value: ValueExpr
    comparison: Literal["gt", "gte", "lt", "lte", "eq"]
    outputs: ThresholdOutputs


class AllOfFlagsOutputs(BaseModel):
    result_key: str


class AllOfFlagsEvaluator(BaseModel):
    """
    여러 boolean 플래그가 모두 True 인지.
    예: householder ∧ no_house ∧ lease_contract
    """

    kind: Literal["all_of_flags"] = "all_of_flags"
    flags: list[str]
    outputs: AllOfFlagsOutputs


Evaluator = Annotated[
    Union[ThresholdEvaluator, AllOfFlagsEvaluator],
    Field(discriminator="kind"),
]


# ---------------- 룰 ----------------


class Rule(BaseModel):
    """외부 JSON 1건."""

    rule_id: str
    title: str
    year: int
    legal_anchor: str = Field(..., description="예: '소득세법 §59의4 ②'")
    legal_text_hash: str | None = Field(
        default=None,
        description="법령 본문 sha256. 법령 API validate_freshness 결과로 채움.",
    )
    source_api_id: str | None = Field(
        default=None,
        description="법령 API 측 식별자 (법령ID 또는 MST + 조항). LLM 컴파일러가 채움.",
    )
    human_reviewed: bool = True
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    compiled_at: str | None = None
    compiled_by: str = Field(default="manual", description="manual | llm:gpt-4o-mini 등")
    evaluator: Evaluator


# ---------------- 평가 결과 ----------------


class RuleEvaluation(BaseModel):
    """룰 1건 평가 결과. Phase 3-1 Provenance 응답의 building block."""

    rule_id: str
    title: str
    legal_anchor: str
    legal_text_hash: str | None = None
    computed: dict[str, Any] = Field(
        default_factory=dict,
        description="rule.evaluator.outputs 매핑 결과 (예: {'card_threshold_25': 10000000, ...})",
    )
    result: bool | None = Field(
        default=None,
        description="True/False/None. None 은 입력 데이터 부족.",
    )
    formula: str | None = None


class RulePack(BaseModel):
    """rules/{year}.json 의 최상위 컨테이너."""

    year: int
    rules: list[Rule]

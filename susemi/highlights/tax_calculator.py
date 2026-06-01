"""
2025년 귀속 한국 근로소득세 환급액 계산기.

== 흐름 ==
총급여 → 근로소득공제 → 근로소득금액 → 인적공제 → 과세표준
      → 누진세율 → 산출세액
      → 근로소득세액공제 + 표준세액공제 + 외부 세액공제 → 결정세액
      → 지방소득세(10%) 합산 → 총 부담세액
      → 기납부세액과 비교 → 환급/추징

== 원칙 ==
- 정수(원 단위) 계산. float 회피.
- 모든 단계가 CalcStep 으로 기록되어 Phase 3-1 Provenance 응답에 그대로 흘려보낼 수 있음.
- 룰 데이터 = `app/data/tax_tables/2025.json` (한도/세율/공제 정액 모두 외부화).

== 검증 상태 ==
- 본 산식은 2024 ~ 2025년 소득세법/시행령 기준으로 작성됨.
- 정확도는 골든셋 테스트로 검증. 실제 적용 전 국세청 모의계산기와 동치성 재확인 권장.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.schemas.tax_calculator_schema import (
    CalcInputs,
    CalcResult,
    CalcStep,
    DependentsInput,
    ItemizedDeductions,
)

DEFAULT_TABLE_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "tax_tables" / "2025.json"
)


@lru_cache(maxsize=4)
def load_tax_table(year: int = 2025, path: str | None = None) -> dict[str, Any]:
    """세율표 캐시 로드. path 인자가 있으면 그 경로 우선."""
    file_path = Path(path) if path else DEFAULT_TABLE_PATH
    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("year") != year and path is None:
        raise ValueError(f"세율표 연도 mismatch: 요청 {year}, 파일 {data.get('year')}")
    return data


# ---------------- 단계별 함수 ----------------


def earned_income_deduction(gross_salary: int, table: dict[str, Any]) -> int:
    """근로소득공제 (소득세법 §47)."""
    cfg = table["earned_income_deduction"]
    cap = cfg["cap"]

    if gross_salary <= 0:
        return 0

    for bracket in cfg["brackets"]:
        upper = bracket["upper"]
        if upper is None or gross_salary <= upper:
            base = bracket["base"]
            fixed = bracket["fixed"]
            rate = bracket["rate"]
            deduction = fixed + int(round((gross_salary - base) * rate))
            return min(deduction, cap)

    raise ValueError("근로소득공제 구간 매칭 실패")


def progressive_tax(taxable_income: int, table: dict[str, Any]) -> int:
    """종합소득세율 적용 (소득세법 §55)."""
    cfg = table["progressive_tax"]

    if taxable_income <= 0:
        return 0

    for bracket in cfg["brackets"]:
        upper = bracket["upper"]
        if upper is None or taxable_income <= upper:
            base = bracket["base"]
            fixed = bracket["fixed"]
            rate = bracket["rate"]
            return fixed + int(round((taxable_income - base) * rate))

    raise ValueError("종합소득세율 구간 매칭 실패")


def personal_deduction(
    deps: DependentsInput, table: dict[str, Any]
) -> tuple[int, dict[str, int]]:
    """
    인적공제 합계 + 항목별 breakdown.
    - 기본: 본인/배우자/부양가족 (각 150만)
    - 추가: 경로(100만)/장애인(200만)/한부모(100만)/부녀자(50만)
    - 한부모와 부녀자는 동시 적용 불가 — 한부모 우선.
    """
    cfg = table["personal_deduction"]
    basic = cfg["basic"]
    additional = cfg["additional"]

    breakdown: dict[str, int] = {}

    if deps.self_eligible:
        breakdown["basic_self"] = basic["self"]
    if deps.spouse:
        breakdown["basic_spouse"] = basic["spouse"]
    if deps.dependents_count > 0:
        breakdown["basic_dependents"] = basic["dependent"] * deps.dependents_count

    if deps.senior_count > 0:
        breakdown["additional_senior"] = additional["senior"] * deps.senior_count
    if deps.disabled_count > 0:
        breakdown["additional_disabled"] = (
            additional["disabled"] * deps.disabled_count
        )

    if deps.single_parent:
        # 한부모 우선, 부녀자 무시
        breakdown["additional_single_parent"] = additional["single_parent"]
    elif deps.female_householder:
        breakdown["additional_female_householder"] = additional[
            "female_householder"
        ]

    return sum(breakdown.values()), breakdown


def earned_income_tax_credit(
    calculated_tax: int,
    gross_salary: int,
    table: dict[str, Any],
) -> int:
    """
    근로소득세액공제 (소득세법 §59).
    1) 산출세액 구간별 비율 적용
    2) 총급여 구간별 한도 적용 (max(공식값, min_cap))
    """
    if calculated_tax <= 0:
        return 0

    cfg = table["earned_income_tax_credit"]

    # 1) 비율 계산
    raw_credit = 0
    for b in cfg["rate_brackets"]:
        upper = b["upper_calculated_tax"]
        if upper is None or calculated_tax <= upper:
            raw_credit = b["fixed"] + int(
                round((calculated_tax - b["base"]) * b["rate"])
            )
            break

    # 2) 한도
    cap = _cap_for_gross(gross_salary, cfg["cap_by_gross"])
    return min(raw_credit, cap)


def _cap_for_gross(gross_salary: int, cap_brackets: list[dict[str, Any]]) -> int:
    for b in cap_brackets:
        upper = b["upper_gross"]
        if upper is not None and gross_salary > upper:
            continue
        # 매칭된 구간
        if "cap" in b:
            return int(b["cap"])
        cap_max = b["cap_max"]
        cap_min = b["cap_min"]
        excess = gross_salary - b["excess_base"]
        deducted = cap_max - int(round(excess * b["deduct_per_excess"]))
        return max(deducted, cap_min)
    raise ValueError("근로세액공제 한도 구간 매칭 실패")


# ---------------- Tier 3-3: 항목별 정밀 산식 ----------------


def _child_tax_credit(
    child_count: int, newborn_count: int, table: dict[str, Any]
) -> int:
    """
    자녀세액공제 (소득세법 §59의2).
    - 1명: 15만, 2명: 30만, 3명 이상: 30만 + (n-2) × 30만
    - 출산·입양: 첫째 30만 / 둘째 50만 / 셋째 이상 70만
    """
    cfg = table["itemized"]["child_tax_credit"]
    out = 0

    if child_count >= 1:
        out += cfg["first_or_second_per_child"]
    if child_count >= 2:
        out += cfg["first_or_second_per_child"]
    if child_count >= 3:
        out += (child_count - 2) * cfg["additional_per_child"]

    nb = cfg["newborn"]
    for n in range(1, newborn_count + 1):
        if n == 1:
            out += nb["first"]
        elif n == 2:
            out += nb["second"]
        else:
            out += nb["third_or_more"]

    return out


def _medical_credit(
    items: ItemizedDeductions, gross_salary: int, table: dict[str, Any]
) -> int:
    """
    의료비 세액공제 (소득세법 §59의4 ②).
    v0 단순화: 모든 의료비를 합쳐 임계값(총급여 3%) 차감 후 15% 적용.
    - 일반 부양가족 의료비는 700만 한도 적용
    - 난임/미숙아 차등 비율은 v1 (현재 모두 15%)
    """
    cfg = table["itemized"]["medical_credit"]
    threshold = int(gross_salary * cfg["threshold_pct_of_gross"])
    cap_general = cfg["general_dependents_cap"]

    capped_general = min(items.medical_general, cap_general)
    total = (
        items.medical_self_etc
        + capped_general
        + items.medical_infertility
        + items.medical_preemie
    )

    excess = max(0, total - threshold)
    if excess <= 0:
        return 0

    return int(round(excess * cfg["rate"]))


def _donation_credit(
    items: ItemizedDeductions,
    earned_income_amount: int,
    table: dict[str, Any],
) -> int:
    """
    기부금 세액공제 (조세특례제한법 §76 / 소득세법 §59의4 ④).
    - 정치자금: 10만 이하 100%, 10만~3000만 15%, 3000만 초과 25%
    - 일반(법정+지정): 1000만 이하 15%, 초과분 30%. 한도 근로소득금액 × 30%.
    """
    cfg = table["itemized"]["donation_credit"]
    pol_cfg = cfg["political"]
    gen_cfg = cfg["general"]

    out = 0

    # 정치자금
    p = items.donation_political
    if p > 0:
        low = pol_cfg["low_threshold"]
        mid = pol_cfg["mid_threshold"]
        if p <= low:
            out += int(round(p * pol_cfg["low_rate"]))
        elif p <= mid:
            out += int(round(low * pol_cfg["low_rate"]))
            out += int(round((p - low) * pol_cfg["mid_rate"]))
        else:
            out += int(round(low * pol_cfg["low_rate"]))
            out += int(round((mid - low) * pol_cfg["mid_rate"]))
            out += int(round((p - mid) * pol_cfg["high_rate"]))

    # 일반 (법정/지정 모두 — 한도 근로소득금액 × 30%)
    g = items.donation_general
    if g > 0:
        cap = int(earned_income_amount * gen_cfg["cap_pct_of_earned_income"])
        capped = min(g, cap)
        high_th = gen_cfg["high_threshold"]
        if capped <= high_th:
            out += int(round(capped * gen_cfg["rate_low"]))
        else:
            out += int(round(high_th * gen_cfg["rate_low"]))
            out += int(round((capped - high_th) * gen_cfg["rate_high"]))

    return out


def compute_itemized(
    items: ItemizedDeductions,
    *,
    gross_salary: int,
    earned_income_amount: int,
    table: dict[str, Any],
) -> tuple[int, dict[str, int]]:
    """ItemizedDeductions → 총 세액공제 + 항목별 breakdown."""
    breakdown: dict[str, int] = {}

    child = _child_tax_credit(
        items.child_count_under_20, items.newborn_count, table
    )
    if child:
        breakdown["child_tax_credit"] = child

    medical = _medical_credit(items, gross_salary, table)
    if medical:
        breakdown["medical_credit"] = medical

    donation = _donation_credit(items, earned_income_amount, table)
    if donation:
        breakdown["donation_credit"] = donation

    return sum(breakdown.values()), breakdown


# ---------------- 통합 함수 ----------------


def calculate(
    inputs: CalcInputs, year: int = 2025, table_path: str | None = None
) -> CalcResult:
    """
    풀 파이프라인. 각 단계 결과를 CalcStep 으로 기록한 CalcResult 반환.
    """
    table = load_tax_table(year=year, path=table_path)
    anchors = table["legal_anchors"]
    steps: list[CalcStep] = []

    # 1) 근로소득공제
    eid = earned_income_deduction(inputs.gross_salary, table)
    steps.append(
        CalcStep(
            name="earned_income_deduction",
            label="근로소득공제",
            legal_anchor=anchors["earned_income_deduction"],
            formula="구간별 정액 + 초과분 비율, 한도 2,000만",
            inputs={"gross_salary": inputs.gross_salary},
            output=eid,
        )
    )

    earned_income_amount = max(0, inputs.gross_salary - eid)
    steps.append(
        CalcStep(
            name="earned_income_amount",
            label="근로소득금액",
            legal_anchor=anchors["earned_income_deduction"],
            formula="총급여 - 근로소득공제",
            inputs={"gross_salary": inputs.gross_salary, "deduction": eid},
            output=earned_income_amount,
        )
    )

    # 2) 인적공제
    pd_total, pd_breakdown = personal_deduction(inputs.dependents, table)
    steps.append(
        CalcStep(
            name="personal_deduction",
            label="인적공제 (기본+추가)",
            legal_anchor=anchors["basic_personal_deduction"],
            formula="본인 + 배우자 + 부양가족 + (경로/장애/한부모|부녀자)",
            inputs=pd_breakdown,
            output=pd_total,
        )
    )

    # 3) 과세표준
    taxable_income = max(
        0,
        earned_income_amount - pd_total - inputs.extra_income_deductions,
    )
    steps.append(
        CalcStep(
            name="taxable_income",
            label="과세표준",
            legal_anchor=None,
            formula="근로소득금액 - 인적공제 - 기타 소득공제",
            inputs={
                "earned_income_amount": earned_income_amount,
                "personal_deduction": pd_total,
                "extra_income_deductions": inputs.extra_income_deductions,
            },
            output=taxable_income,
        )
    )

    # 4) 산출세액
    calculated_tax = progressive_tax(taxable_income, table)
    steps.append(
        CalcStep(
            name="calculated_tax",
            label="산출세액",
            legal_anchor=anchors["progressive_tax"],
            formula="과세표준 구간별 정액 + 초과분 비율 (6%~45%)",
            inputs={"taxable_income": taxable_income},
            output=calculated_tax,
        )
    )

    # 5) 근로소득세액공제
    eitc = earned_income_tax_credit(
        calculated_tax, inputs.gross_salary, table
    )
    steps.append(
        CalcStep(
            name="earned_income_tax_credit",
            label="근로소득세액공제",
            legal_anchor=anchors["earned_income_tax_credit"],
            formula="산출세액 비율 (55% 또는 71.5만+30%) + 총급여 기준 한도",
            inputs={
                "calculated_tax": calculated_tax,
                "gross_salary": inputs.gross_salary,
            },
            output=eitc,
        )
    )

    # 6) 표준세액공제
    standard_credit = (
        table["standard_tax_credit"]["amount"]
        if inputs.use_standard_tax_credit
        else 0
    )
    steps.append(
        CalcStep(
            name="standard_tax_credit",
            label="표준세액공제",
            legal_anchor=anchors["standard_tax_credit"],
            formula="13만 (특별세액공제 미선택 시)" if standard_credit else "미적용",
            inputs={"applied": inputs.use_standard_tax_credit},
            output=standard_credit,
        )
    )

    # 7) 외부 세액공제 — itemized 우선, 없으면 extra_tax_credits 합산값
    itemized_breakdown: dict[str, int] = {}
    if inputs.itemized is not None:
        effective_extra, itemized_breakdown = compute_itemized(
            inputs.itemized,
            gross_salary=inputs.gross_salary,
            earned_income_amount=earned_income_amount,
            table=table,
        )
        steps.append(
            CalcStep(
                name="itemized_tax_credits",
                label="기타 세액공제 (항목별)",
                legal_anchor="소득세법 §59의2 / §59의4",
                formula="자녀 + 의료비 + 기부금 (각 한도/비율 적용)",
                inputs={"breakdown": itemized_breakdown},
                output=effective_extra,
            )
        )
    else:
        effective_extra = inputs.extra_tax_credits
        if effective_extra:
            steps.append(
                CalcStep(
                    name="extra_tax_credits",
                    label="기타 세액공제 (외부 합산)",
                    legal_anchor=None,
                    formula="외부에서 합산해 전달된 값을 그대로 차감",
                    inputs={"amount": effective_extra},
                    output=effective_extra,
                )
            )

    # 8) 결정세액 (국세분)
    determined_tax = max(
        0,
        calculated_tax - eitc - standard_credit - effective_extra,
    )
    steps.append(
        CalcStep(
            name="determined_tax",
            label="결정세액 (국세)",
            legal_anchor=None,
            formula="산출세액 - (근로세액공제 + 표준세액공제 + 기타 세액공제), 0 이상",
            inputs={
                "calculated_tax": calculated_tax,
                "earned_income_tax_credit": eitc,
                "standard_tax_credit": standard_credit,
                "extra_tax_credits": effective_extra,
            },
            output=determined_tax,
        )
    )

    # 9) 지방소득세
    local_rate = table["local_income_tax"]["rate"]
    local_tax = int(round(determined_tax * local_rate))
    steps.append(
        CalcStep(
            name="local_income_tax",
            label="지방소득세",
            legal_anchor=anchors["local_income_tax"],
            formula=f"결정세액 × {local_rate * 100:.0f}%",
            inputs={"determined_tax": determined_tax},
            output=local_tax,
        )
    )

    total_tax = determined_tax + local_tax
    refund = inputs.prepaid_tax - total_tax
    steps.append(
        CalcStep(
            name="refund_or_owed",
            label="환급/추징",
            legal_anchor=None,
            formula="기납부세액 - 총 부담세액 (양수=환급, 음수=추징)",
            inputs={
                "prepaid_tax": inputs.prepaid_tax,
                "total_tax": total_tax,
            },
            output=refund,
        )
    )

    return CalcResult(
        earned_income_deduction=eid,
        earned_income_amount=earned_income_amount,
        personal_deduction=pd_total,
        taxable_income=taxable_income,
        calculated_tax=calculated_tax,
        earned_income_tax_credit=eitc,
        standard_tax_credit=standard_credit,
        extra_tax_credits=effective_extra,
        determined_tax=determined_tax,
        local_income_tax=local_tax,
        total_tax=total_tax,
        prepaid_tax=inputs.prepaid_tax,
        refund_or_owed=refund,
        itemized_breakdown=itemized_breakdown,
        steps=steps,
        year=table.get("year", year),
    )

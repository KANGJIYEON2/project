from fastapi import APIRouter, Request

from app.rate_limit import LIMIT_LLM_USER, limiter
from app.schemas.analysis_schema import AnalyzeRequest, AnalyzeResponse, Section
from app.schemas.rag_schema import SearchHit
from app.schemas.rule_schema import RuleEvaluation
from app.schemas.tax_calculator_schema import CalcInputs, CalcResult, DependentsInput
from app.services import rag
from app.services.llm_client import generate_analysis
from app.services.rules_engine import RuleContext, build_rule_context
from app.services.tax_calculator import calculate

router = APIRouter()


# 섹션 → 관련 룰 ID 매핑 (Phase 3-1 Provenance).
# 룰이 추가되면 여기에 등록해야 해당 섹션에 anchor 가 붙음.
SECTION_TO_RULE_IDS: dict[str, list[str]] = {
    "card": ["card_25_threshold"],
    "medical": ["medical_3_threshold"],
    "rent_loan": ["rent_eligibility"],
    "donation": [],
    "other": [],
}


# RAG 컨텍스트 fetch 시 검색에 쓸 top-K
RAG_TOP_K = 8


def _attach_provenance(
    sections: list[Section],
    evaluations: list[RuleEvaluation],
) -> list[Section]:
    """섹션 ID 기준으로 룰 평가 결과를 provenance 로 부착."""
    by_id = {ev.rule_id: ev for ev in evaluations}
    out: list[Section] = []
    for sec in sections:
        wanted = SECTION_TO_RULE_IDS.get(sec.id, [])
        prov = [by_id[rid] for rid in wanted if rid in by_id]
        out.append(sec.model_copy(update={"provenance": prov}))
    return out


def _build_rag_query(rule_context: RuleContext) -> str | None:
    """평가된 룰들의 제목·anchor 를 합쳐 RAG 검색 query 로 사용."""
    if not rule_context.evaluations:
        return None
    parts: list[str] = []
    for ev in rule_context.evaluations:
        parts.append(ev.title)
        if ev.legal_anchor:
            parts.append(ev.legal_anchor)
    query = " ".join(parts).strip()
    return query or None


async def _fetch_rag_context(
    rule_context: RuleContext,
    top_k: int = RAG_TOP_K,
) -> list[SearchHit]:
    """
    RAG top-K 법령 청크 fetch. 실패 시 빈 리스트 반환 (분석 흐름 유지).
    인덱스가 비었거나 OPENAI_API_KEY 없으면 자연스럽게 [] 반환.
    """
    query = _build_rag_query(rule_context)
    if query is None:
        return []
    try:
        hits, _ = await rag.search(query, top_k=top_k)
        return hits
    except Exception:
        # RAG 실패는 분석 자체를 막지 않음 — silent fallback
        return []


def _run_tax_calc(data: AnalyzeRequest) -> CalcResult | None:
    """사용자 입력 → CalcInputs 변환 → tax_calculator 실행. 실패 시 None."""
    try:
        # total_salary 는 이미 비과세 제외(총급여) — verify/simulate/recommend 와 동일하게
        # non_taxable 을 다시 빼지 않는다 (이중차감 → 세액 과소 버그였음).
        gross = data.income.total_salary or 0
        if gross <= 0:
            return None
        inputs = CalcInputs(
            gross_salary=gross,
            non_taxable=data.income.non_taxable or 0,
            dependents=DependentsInput(
                spouse=data.dependents.has_spouse or False,
                dependents_count=data.dependents.dependents_count or 0,
                senior_count=data.dependents.senior_count or 0,
                disabled_count=data.dependents.disabled_count or 0,
                female_householder=data.dependents.female_householder or False,
                single_parent=data.dependents.single_parent or False,
            ),
            prepaid_tax=data.parsed_pdf.prepaid_tax or 0,
        )
        return calculate(inputs)
    except Exception:
        return None


@router.post("/analyze", response_model=AnalyzeResponse)
@limiter.limit(LIMIT_LLM_USER)
async def analyze_tax(request: Request, data: AnalyzeRequest):
    """
    PAGE 7: 전체 데이터 기반 Why 분석.
    1) 규칙엔진: JSON 룰 평가 → RuleEvaluation 리스트 (각각 legal_anchor 포함)
    2) RAG: 평가된 룰의 제목/anchor 로 법령 본문 top-K fetch (실패시 silent skip)
    3) LLM: 항목별 Why 해설 (detail 안에 [rule_id] 마커 인용 + RAG 본문 참고)
    4) 백엔드 후처리: 섹션마다 관련 평가 결과를 provenance 로 부착
    """

    rule_context = build_rule_context(
        income=data.income,
        dependents=data.dependents,
        conditions=data.conditions,
        parsed_pdf=data.parsed_pdf,
        manual_input=data.manual_input,
    )

    # 세금 산식 실행 — LLM 이 실제 세액을 참조할 수 있게
    calc_result = _run_tax_calc(data)

    rag_hits = await _fetch_rag_context(rule_context)

    summary, sections, tax_tips = await generate_analysis(
        income=data.income,
        dependents=data.dependents,
        conditions=data.conditions,
        parsed_pdf=data.parsed_pdf,
        manual_input=data.manual_input,
        rule_context=rule_context,
        rag_hits=rag_hits,
        calc_result=calc_result,
    )

    # Provenance 부착 — LLM 결과는 변경하지 않고 새 Section 객체로 복제
    sections_with_prov = _attach_provenance(sections, rule_context.evaluations)

    return AnalyzeResponse(
        summary=summary,
        sections=sections_with_prov,
        tax_tips=tax_tips,
        evaluations=rule_context.evaluations,
    )

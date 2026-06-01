"""Triage 서비스: LLM 호출 결과를 Triage 엔티티로 영속화 + 비용 트래킹.

- P0 이중 검증: LLM이 P0로 분류했더라도 키워드 미매칭 시 P1로 강등.
- 매 LLM 호출은 LLMUsage 테이블에 기록 (services/usage.py 가 집계).
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlmodel import Session

from app.llm.client import classify_review
from app.llm.pricing import compute_cost
from app.models import LLMUsage, Review, Severity, Triage, TriageStatus

logger = logging.getLogger(__name__)

# 운영팀과 합의된 P0 신호 키워드. LLM이 P0로 분류했을 때 본문에 아래 중 하나라도
# 포함되어야 P0 확정.
P0_KEYWORDS: tuple[str, ...] = (
    "의료사고",
    "오진",
    "오처방",
    "감염",
    "낙상",
    "수술 실패",
    "수술 부작용",
    "약 잘못",
    "약물 오투여",
    "응급",
    "사망",
    "위험",
    "고소",
    "소송",
    "환자 안전",
    "의료 과실",
    "의료 사고",
    "패혈증",
    "합병증",
)


def finalize_severity(llm_severity: Severity, content: str) -> Severity:
    """P0 이중 검증. P0가 아니면 그대로 반환."""
    if llm_severity != Severity.P0:
        return llm_severity
    if any(kw in content for kw in P0_KEYWORDS):
        return Severity.P0
    logger.info(
        "p0.downgraded_to_p1",
        extra={"reason": "no_p0_keyword_hit", "content_preview": content[:120]},
    )
    return Severity.P1


async def run_triage(session: Session, review: Review, model: str | None = None) -> Triage:
    output, metrics = await classify_review(
        content=review.content,
        rating=review.rating,
        source=review.source,
        model=model,
    )

    # 호출 비용 영속화 (실패해도 다른 흐름 막지 않도록 동일 트랜잭션 안에서)
    usage = LLMUsage(
        review_id=review.id,
        model=metrics.model,
        prompt_tokens=metrics.prompt_tokens,
        completion_tokens=metrics.completion_tokens,
        total_tokens=metrics.total_tokens,
        cost_usd=compute_cost(
            metrics.model, metrics.prompt_tokens, metrics.completion_tokens
        ),
    )
    session.add(usage)

    final_severity = finalize_severity(output.severity, review.content)

    triage = Triage(
        review_id=review.id,
        category=output.category,
        severity=final_severity,
        sentiment_score=output.sentiment_score,
        assigned_team=output.assigned_team,
        summary=output.summary,
        tags=output.tags,
        model=metrics.model,
        confidence=output.confidence,
    )
    session.add(triage)
    review.triage_status = TriageStatus.DONE
    session.add(review)
    session.commit()
    session.refresh(triage)
    return triage


def mark_failed(session: Session, review_id: UUID) -> None:
    review = session.get(Review, review_id)
    if review is None:
        return
    review.triage_status = TriageStatus.FAILED
    session.add(review)
    session.commit()

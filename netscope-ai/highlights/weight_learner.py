"""
Online score adjustment (L4).

Simple increment-based weight learning from user feedback.
Applies safety guards to prevent score manipulation:
- score_adjust absolute value capped at ±0.10
- Per-update delta capped at ±0.02
- Same-user repeated feedback has diminishing effect

Future: upgrade to logistic regression when enough data accumulates.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from src.model.pattern import Pattern, PatternFeedback


# Safety bounds
MAX_ADJUST = 0.10       # |score_adjust| <= 0.10
CONFIRM_DELTA = 0.01    # +0.01 per confirm
DISMISS_DELTA = -0.01   # -0.01 per dismiss
WRONG_DELTA = -0.02     # -0.02 per wrong-match

# Diminishing returns: same user's Nth feedback has weight 1/N
MAX_SAME_USER_WEIGHT = 5  # After 5 feedbacks, weight becomes 1/5


def apply_feedback_adjustment(
    db: Session,
    pattern: Pattern,
    action: str,
    user_id: str | None = None,
) -> float:
    """
    Apply score adjustment based on feedback action.
    Returns the new score_adjust value.
    """
    # Calculate diminishing weight for same-user feedback
    weight = 1.0
    if user_id:
        same_user_count = (
            db.query(PatternFeedback)
            .filter(
                # pattern_id 는 복합 PK 도입으로 테넌트 간 비유일 → tenant_id 동시 필터 필수
                PatternFeedback.tenant_id == pattern.tenant_id,
                PatternFeedback.pattern_id == pattern.id,
                PatternFeedback.user_id == user_id,
            )
            .count()
        )
        if same_user_count > 1:
            weight = 1.0 / min(same_user_count, MAX_SAME_USER_WEIGHT)

    # Determine delta
    if action == "confirm":
        delta = CONFIRM_DELTA * weight
    elif action == "dismiss":
        delta = DISMISS_DELTA * weight
    elif action == "wrong":
        delta = WRONG_DELTA * weight
    else:
        return pattern.score_adjust

    # Apply with safety bounds
    new_adjust = pattern.score_adjust + delta
    new_adjust = max(-MAX_ADJUST, min(MAX_ADJUST, new_adjust))
    new_adjust = round(new_adjust, 4)

    pattern.score_adjust = new_adjust
    db.commit()

    return new_adjust


def effective_score(pattern: Pattern) -> float:
    """Calculate effective score for a pattern (seed + adjustment)."""
    return max(0.0, pattern.score_seed + pattern.score_adjust)

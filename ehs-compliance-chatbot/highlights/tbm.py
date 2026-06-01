"""TBM (Tool Box Meeting) 라우터 — AI 안건 자동 생성"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.user import User
from app.models.site import Site
from app.models.incident import Incident
from app.models.tbm import TBMSession, TBMAttendee
from app.dependencies import get_current_user

router = APIRouter(prefix="/api/tbm", tags=["tbm"])


def _assert_site_in_company(db: Session, site_id: str, user: User) -> Site:
    """site 가 호출자 회사 소속인지 검증 (cross-tenant 차단). 아니면 404."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site or site.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="사업장을 찾을 수 없습니다")
    return site

TYPE_LABELS = {
    "caught": "끼임", "fall": "추락", "collision": "충돌", "electric": "감전",
    "fire": "화재", "suffocation": "질식", "falling_object": "낙하물",
    "chemical": "화학물질", "other": "기타",
}


class TBMCreateRequest(BaseModel):
    site_id: str
    process_name: str | None = None
    date: str | None = None  # YYYY-MM-DD, 없으면 오늘


class AttendeeRequest(BaseModel):
    user_name: str = Field(..., min_length=1)


@router.post("/generate")
def generate_tbm(
    req: TBMCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """오늘의 TBM 안건 AI 자동 생성"""
    site = db.query(Site).filter(Site.id == req.site_id).first()
    if not site or site.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="사업장을 찾을 수 없습니다")

    date = req.date or datetime.utcnow().strftime("%Y-%m-%d")

    # 이미 오늘 생성된 TBM 있으면 반환
    existing = (
        db.query(TBMSession)
        .options(joinedload(TBMSession.attendees))
        .filter(TBMSession.site_id == req.site_id, TBMSession.date == date)
        .first()
    )
    if existing:
        return _format_tbm(existing)

    # 최근 사고 이력 조회
    recent = (
        db.query(Incident)
        .filter(Incident.site_id == req.site_id)
        .order_by(Incident.occurred_at.desc())
        .limit(5)
        .all()
    )
    recent_text = "\n".join(
        f"- [{TYPE_LABELS.get(i.incident_type, i.incident_type)}] {i.description[:60]} ({i.occurred_at.strftime('%m/%d')})"
        for i in recent
    ) if recent else "최근 사고 이력 없음"

    # AI 안건 생성
    agenda = {"cautions": [], "checklist": [], "special_notes": []}
    try:
        from app.main import incident_agent
        if incident_agent.is_ready:
            result = incident_agent._chat_json(f"""오늘의 TBM(Tool Box Meeting) 안건을 생성하라.

사업장: {site.name}
{f'공정: {req.process_name}' if req.process_name else ''}
날짜: {date}

최근 사고 이력:
{recent_text}

JSON으로 반환:
{{
  "cautions": ["최근 사고 기반 주의사항 2-3개"],
  "checklist": ["작업 전 점검 항목 4-5개"],
  "special_notes": ["오늘의 특별 안전 유의사항 1-2개"]
}}

현장 작업자가 바로 이해할 수 있는 쉬운 표현으로. JSON만 반환.""")
            agenda = result
    except Exception:
        agenda = {
            "cautions": ["최근 사고 이력을 확인하고 유사 위험에 주의하세요"],
            "checklist": ["개인보호구 착용 확인", "장비 작동 상태 점검", "비상구/소화기 위치 확인", "작업 절차 숙지"],
            "special_notes": ["안전 수칙을 준수합시다"],
        }

    session = TBMSession(
        site_id=req.site_id,
        created_by=user.id,
        date=date,
        process_name=req.process_name,
        agenda=json.dumps(agenda, ensure_ascii=False),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return _format_tbm(session)


@router.get("/today")
def get_today_tbm(
    site_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """오늘의 TBM 조회"""
    _assert_site_in_company(db, site_id, user)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    session = (
        db.query(TBMSession)
        .options(joinedload(TBMSession.attendees))
        .filter(TBMSession.site_id == site_id, TBMSession.date == today)
        .first()
    )
    if not session:
        return {"session": None}
    return _format_tbm(session)


@router.get("/history")
def get_tbm_history(
    site_id: str,
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """TBM 히스토리"""
    _assert_site_in_company(db, site_id, user)
    sessions = (
        db.query(TBMSession)
        .options(joinedload(TBMSession.attendees))
        .filter(TBMSession.site_id == site_id)
        .order_by(TBMSession.date.desc())
        .limit(limit)
        .all()
    )
    return [_format_tbm(s) for s in sessions]


@router.post("/{session_id}/attend")
def add_attendee(
    session_id: str,
    req: AttendeeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """TBM 참석 서명"""
    session = db.query(TBMSession).filter(TBMSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404)
    # cross-tenant 차단: 세션의 사업장이 호출자 회사 소속인지 검증
    _assert_site_in_company(db, session.site_id, user)

    attendee = TBMAttendee(
        session_id=session_id,
        user_name=req.user_name,
        acknowledged=True,
        acknowledged_at=datetime.utcnow(),
    )
    db.add(attendee)

    # 포인트 적립 (+30)
    try:
        from app.models.gamification import SafetyPoint
        sp = SafetyPoint(user_id=user.id, site_id=session.site_id, points=30, reason="tbm", reference_id=session_id)
        db.add(sp)
    except Exception:
        pass

    db.commit()
    return {"status": "ok", "attendee": req.user_name}


def _format_tbm(session: TBMSession) -> dict:
    return {
        "id": session.id,
        "site_id": session.site_id,
        "date": session.date,
        "process_name": session.process_name,
        "agenda": json.loads(session.agenda),
        "attendees": [
            {"name": a.user_name, "acknowledged": a.acknowledged, "at": a.acknowledged_at.isoformat() if a.acknowledged_at else None}
            for a in session.attendees
        ],
        "attendee_count": len(session.attendees),
        "created_at": session.created_at.isoformat(),
    }

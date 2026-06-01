"""공통 의존성: 인증, 권한 체크"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models.user import User, UserRole
from app.services.auth_service import decode_token

security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="인증 토큰이 필요합니다"
        )
    payload = decode_token(credentials.credentials, settings)
    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않은 토큰입니다"
        )
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="사용자를 찾을 수 없습니다"
        )
    return user


def require_role(*roles: UserRole):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in [r.value for r in roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="권한이 부족합니다"
            )
        return user

    return checker

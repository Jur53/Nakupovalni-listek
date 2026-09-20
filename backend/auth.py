from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import User


password_hash = PasswordHash.recommended()
dummy_password_hash = password_hash.hash("dummy-password-never-used")
bearer = HTTPBearer(auto_error=False)


class AuthRateLimiter:
    def __init__(self):
        self._attempts: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()

    def check(self, request: Request, action: str) -> None:
        settings = get_settings()
        limit = settings.login_rate_limit if action == "login" else settings.register_rate_limit
        client = request.client.host if request.client else "unknown"
        key = f"{action}:{client}"
        now = monotonic()
        cutoff = now - settings.auth_rate_limit_window_seconds
        with self._lock:
            attempts = self._attempts.pop(key, deque())
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= limit:
                self._attempts[key] = attempts
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many authentication attempts",
                    headers={"Retry-After": str(settings.auth_rate_limit_window_seconds)},
                )
            attempts.append(now)
            self._attempts[key] = attempts
            while len(self._attempts) > settings.auth_rate_limit_max_keys:
                self._attempts.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._attempts.clear()


auth_rate_limiter = AuthRateLimiter()


def check_auth_rate_limit(request: Request, action: str) -> None:
    auth_rate_limiter.check(request, action)


def verify_login_password(user: User | None, password: str) -> bool:
    eligible = user is not None and user.is_active and not user.is_legacy
    candidate_hash = user.password_hash if eligible else dummy_password_hash
    try:
        verified = password_hash.verify(password, candidate_hash)
    except (PwdlibError, TypeError, ValueError):
        verified = False
    return bool(eligible and verified)


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def create_access_token(user_id: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expiry_minutes),
        "iss": "nakupovalni-listek",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized
    try:
        payload = jwt.decode(
            credentials.credentials,
            get_settings().jwt_secret,
            algorithms=["HS256"],
            issuer="nakupovalni-listek",
        )
        user_id = int(payload["sub"])
    except (InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized
    user = db.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
    if user is None or user.is_legacy:
        raise unauthorized
    return user

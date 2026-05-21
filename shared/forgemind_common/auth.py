"""Minimal JWT auth helpers + role-based access decorators."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from pydantic import BaseModel

from .config import get_settings

Role = Literal["viewer", "operator", "engineer", "admin"]


def _auth_disabled() -> bool:
    """Return True when auth enforcement is disabled (dev/test only)."""
    return os.environ.get("ENABLE_AUTH", "true").lower() in ("false", "0", "no")


class TokenPayload(BaseModel):
    sub: str
    role: Role
    exp: int


def create_access_token(subject: str, role: Role = "viewer") -> str:
    s = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=s.jwt_expiry_minutes)
    payload = {"sub": subject, "role": role, "exp": int(expire.timestamp())}
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_token(token: str) -> TokenPayload:
    s = get_settings()
    try:
        decoded = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
        return TokenPayload(**decoded)
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc


async def require_user(
    authorization: Annotated[str | None, Header()] = None,
) -> TokenPayload:
    if _auth_disabled():
        return TokenPayload(sub="anonymous", role="admin", exp=0)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    return decode_token(authorization.split(" ", 1)[1])


def require_role(*roles: Role):
    async def _dep(user: Annotated[TokenPayload, Depends(require_user)]) -> TokenPayload:
        if _auth_disabled():
            return user
        if user.role not in roles and user.role != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return _dep


# Convenience dependency for admin-only endpoints
require_admin = require_role("admin")

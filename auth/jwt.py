"""
JWT encode / decode and FastAPI dependency.

Tokens are HS256-signed, contain `sub` (subject / user identifier) and
`roles` (list of role strings).  The dependency `get_current_user` is
injected into route handlers that require authentication.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from shared.config import settings

_bearer = HTTPBearer(auto_error=True)


# ---------------------------------------------------------------------------
# Token data model
# ---------------------------------------------------------------------------

class TokenData(BaseModel):
    subject: str
    roles: list[str] = []
    expires_at: datetime


# ---------------------------------------------------------------------------
# Encode
# ---------------------------------------------------------------------------

def create_access_token(subject: str, roles: list[str] | None = None) -> str:
    """
    Create a signed JWT.  `subject` is typically a user ID or service name.
    `roles` maps to RBAC policies in auth/rbac.py.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_expiry_minutes)
    payload = {
        "sub": subject,
        "roles": roles or [],
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


# ---------------------------------------------------------------------------
# Decode
# ---------------------------------------------------------------------------

def decode_token(token: str) -> TokenData:
    """
    Validate and decode a JWT.  Raises `HTTPException 401` on any failure
    (expired, bad signature, missing fields).
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    exp = payload.get("exp")
    expires_at = (
        datetime.fromtimestamp(exp, tz=timezone.utc)
        if exp
        else datetime.now(timezone.utc)
    )

    return TokenData(
        subject=sub,
        roles=payload.get("roles") or [],
        expires_at=expires_at,
    )


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> TokenData:
    """
    FastAPI dependency.  Extracts the Bearer token from the Authorization
    header, decodes it, and returns `TokenData`.

    Usage::

        @router.get("/protected")
        async def protected(user: TokenData = Depends(get_current_user)):
            ...
    """
    return decode_token(credentials.credentials)

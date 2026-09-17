from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from outreach.config import get_settings
from outreach.enums import Role

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    hospital_id: uuid.UUID | None
    role: Role


def create_access_token(principal: Principal) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(principal.user_id),
            "hospital_id": str(principal.hospital_id) if principal.hospital_id else None,
            "role": principal.role.value,
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_token_minutes),
            "iss": "multi-hospital-outreach",
        },
        settings.app_secret,
        algorithm="HS256",
    )


def current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Principal:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        claims = jwt.decode(
            credentials.credentials,
            get_settings().app_secret,
            algorithms=["HS256"],
            issuer="multi-hospital-outreach",
        )
        return Principal(
            user_id=uuid.UUID(claims["sub"]),
            hospital_id=uuid.UUID(claims["hospital_id"]) if claims.get("hospital_id") else None,
            role=Role(claims["role"]),
        )
    except (jwt.PyJWTError, KeyError, ValueError):
        pass

    settings = get_settings()
    if settings.supabase_auth_enabled and settings.supabase_url and settings.supabase_anon_key:
        try:
            response = httpx.get(
                f"{settings.supabase_url.rstrip('/')}/auth/v1/user",
                headers={
                    "apikey": settings.supabase_anon_key,
                    "Authorization": f"Bearer {credentials.credentials}",
                },
                timeout=3,
            )
            response.raise_for_status()
            user = response.json()
            metadata = user.get("app_metadata", {})
            return Principal(
                user_id=uuid.UUID(user["id"]),
                hospital_id=(
                    uuid.UUID(metadata["hospital_id"]) if metadata.get("hospital_id") else None
                ),
                role=Role(metadata["role"]),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            pass
    raise HTTPException(status_code=401, detail="Invalid or expired token")


def require_roles(*roles: Role):
    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return principal

    return dependency


def enforce_tenant(principal: Principal, hospital_id: uuid.UUID) -> None:
    if principal.role != Role.PLATFORM_ADMIN and principal.hospital_id != hospital_id:
        raise HTTPException(status_code=403, detail="Tenant access denied")

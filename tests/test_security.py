import uuid

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from outreach.config import get_settings
from outreach.enums import Role
from outreach.security import (
    Principal,
    create_access_token,
    current_principal,
    enforce_tenant,
)


def test_token_round_trip_shape() -> None:
    principal = Principal(uuid.uuid4(), uuid.uuid4(), Role.HOSPITAL_ADMIN)
    token = create_access_token(principal)
    assert isinstance(token, str)
    assert token.count(".") == 2


def test_tenant_user_cannot_cross_boundary() -> None:
    principal = Principal(uuid.uuid4(), uuid.uuid4(), Role.CAMPAIGN_MANAGER)
    with pytest.raises(HTTPException) as error:
        enforce_tenant(principal, uuid.uuid4())
    assert error.value.status_code == 403


def test_platform_admin_can_cross_boundary() -> None:
    principal = Principal(uuid.uuid4(), None, Role.PLATFORM_ADMIN)
    enforce_tenant(principal, uuid.uuid4())


def test_supabase_identity_uses_protected_app_metadata(monkeypatch) -> None:
    user_id = uuid.uuid4()
    hospital_id = uuid.uuid4()
    monkeypatch.setenv("SUPABASE_AUTH_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "synthetic-anon-key")
    get_settings.cache_clear()

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "id": str(user_id),
                "app_metadata": {
                    "hospital_id": str(hospital_id),
                    "role": "clinical_reviewer",
                },
                "user_metadata": {"role": "platform_admin"},
            }

    monkeypatch.setattr("outreach.security.httpx.get", lambda *args, **kwargs: Response())
    principal = current_principal(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="external-token")
    )

    assert principal.user_id == user_id
    assert principal.hospital_id == hospital_id
    assert principal.role == Role.CLINICAL_REVIEWER
    get_settings.cache_clear()

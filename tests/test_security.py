import uuid

import pytest
from fastapi import HTTPException

from outreach.enums import Role
from outreach.security import Principal, create_access_token, enforce_tenant


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

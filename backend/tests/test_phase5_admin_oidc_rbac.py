from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app.adapter.oidc_staff_auth import OidcStaffAuthenticator, OidcTokenValidator
from app.api.admin_auth import (
    get_staff_authenticator_http,
    require_admin_operator,
    require_admin_role,
    require_admin_viewer,
)
from app.core.settings_admin import AdminSettings
from app.domain.enums.enums import StaffRole
from app.domain.errors.errors import (
    InactiveStaffError,
    InvalidStaffTokenError,
    StaffServiceScopeError,
    UnknownStaffIdentityError,
)
from app.domain.models.staff import (
    AuthenticatedStaff,
    StaffIdentity,
    StaffServicePermission,
)

ISSUER = "https://idp.example.test"
AUDIENCE = "silver-admin"


class Repository:
    def __init__(self, *, active=True, known=True, permissions=None):
        self.staff_id = uuid4()
        self.active = active
        self.known = known
        self.permissions = permissions or (("service-a", StaffRole.OPERATOR),)

    async def find_by_oidc_identity(self, issuer, subject):
        if not self.known or (issuer, subject) != (ISSUER, "subject-1"):
            return None
        identity = StaffIdentity(
            self.staff_id, issuer, subject, "ignored@example.test", "Staff", self.active
        )
        return identity, tuple(
            StaffServicePermission(self.staff_id, service_id, role)
            for service_id, role in self.permissions
        )


@pytest.fixture
def oidc_material():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    jwk["kid"] = "key-1"

    def token(**overrides):
        now = datetime.now(timezone.utc)
        claims = {
            "iss": ISSUER,
            "sub": "subject-1",
            "aud": AUDIENCE,
            "exp": now + timedelta(minutes=5),
            "nbf": now - timedelta(seconds=1),
        }
        claims.update(overrides)
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "key-1"})

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"keys": [jwk]})
    )
    return token, httpx.AsyncClient(transport=transport)


async def _auth(oidc_material, repository=None, service_id=None, token_overrides=None):
    issue, client = oidc_material
    validator = OidcTokenValidator(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_url="https://idp.example.test/jwks",
        algorithms=("RS256",),
        client=client,
    )
    authenticator = OidcStaffAuthenticator(
        token=issue(**(token_overrides or {})),
        requested_service_id=service_id,
        validator=validator,
        repository=repository or Repository(),
    )
    return await authenticator.get_current_staff()


@pytest.mark.asyncio
async def test_valid_signed_token_maps_by_issuer_and_subject(oidc_material):
    staff = await _auth(oidc_material)
    assert staff.role is StaffRole.OPERATOR
    assert staff.service_id == "service-a"
    assert not hasattr(staff, "token")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://wrong.example.test"},
        {"aud": "wrong-audience"},
        {"exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        {"nbf": datetime.now(timezone.utc) + timedelta(minutes=5)},
    ],
)
async def test_invalid_registered_claims_fail_closed(oidc_material, overrides):
    with pytest.raises(InvalidStaffTokenError):
        await _auth(oidc_material, token_overrides=overrides)


@pytest.mark.asyncio
async def test_invalid_signature_and_alg_none_fail_closed(oidc_material):
    _, client = oidc_material
    validator = OidcTokenValidator(
        issuer=ISSUER, audience=AUDIENCE,
        jwks_url="https://idp.example.test/jwks", algorithms=("RS256",), client=client,
    )
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    bad = jwt.encode(
        {"iss": ISSUER, "sub": "subject-1", "aud": AUDIENCE, "exp": now + timedelta(minutes=5)},
        other_key, algorithm="RS256", headers={"kid": "key-1"},
    )
    with pytest.raises(InvalidStaffTokenError):
        await validator.validate(bad)
    with pytest.raises(ValueError):
        OidcTokenValidator(
            issuer=ISSUER, audience=AUDIENCE,
            jwks_url="https://idp.example.test/jwks", algorithms=("none",), client=client,
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_unknown_and_inactive_staff_are_distinct_denials(oidc_material):
    with pytest.raises(UnknownStaffIdentityError):
        await _auth(oidc_material, Repository(known=False))
    with pytest.raises(InactiveStaffError):
        await _auth(oidc_material, Repository(active=False))


@pytest.mark.asyncio
async def test_service_scope_uses_persisted_permissions(oidc_material):
    repository = Repository(
        permissions=(("service-a", StaffRole.VIEWER), ("service-b", StaffRole.ADMIN))
    )
    assert (await _auth(oidc_material, repository, "service-b")).service_id == "service-b"
    with pytest.raises(StaffServiceScopeError):
        await _auth(oidc_material, repository, "service-c")
    with pytest.raises(StaffServiceScopeError):
        await _auth(oidc_material, repository)


@pytest.mark.asyncio
async def test_rbac_viewer_operator_admin():
    viewer = AuthenticatedStaff("v", "Viewer", StaffRole.VIEWER, "s", True)
    operator = AuthenticatedStaff("o", "Operator", StaffRole.OPERATOR, "s", True)
    admin = AuthenticatedStaff("a", "Admin", StaffRole.ADMIN, "s", True)
    assert await require_admin_viewer(viewer) is viewer
    with pytest.raises(HTTPException) as denied:
        await require_admin_operator(viewer)
    assert denied.value.status_code == 403
    assert await require_admin_operator(operator) is operator
    assert await require_admin_operator(admin) is admin
    assert await require_admin_role(admin) is admin
    with pytest.raises(HTTPException) as insufficient:
        await require_admin_role(operator)
    assert insufficient.value.status_code == 403


def test_production_missing_token_and_disabled_oidc_fail_closed():
    settings = AdminSettings(app_env="production", admin_oidc_enabled=False)
    with pytest.raises(HTTPException) as missing:
        get_staff_authenticator_http(None, None, settings, Repository())
    assert missing.value.status_code == 401

    credentials = type("Credentials", (), {"credentials": "opaque"})()
    with pytest.raises(HTTPException) as disabled:
        get_staff_authenticator_http(credentials, None, settings, Repository())
    assert disabled.value.status_code == 503
    assert disabled.value.detail == {"error": "staff_auth_unavailable"}

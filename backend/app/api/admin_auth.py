"""Admin-only authentication and authorization dependencies."""

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.settings_admin import AdminSettings, admin_settings
from app.domain.enums.enums import StaffRole
from app.domain.errors.errors import (
    InactiveStaffError, InvalidStaffTokenError, StaffAuthenticationError,
    StaffServiceScopeError, StaffUnavailableError, UnknownStaffIdentityError,
)
from app.domain.models.staff import AuthenticatedStaff
from app.domain.ports.staff_auth import StaffAuthenticator

_bearer = HTTPBearer(auto_error=False)


def get_staff_authenticator() -> StaffAuthenticator:
    """Compatibility helper for tests and integrated non-production runtime."""
    if admin_settings.app_env.strip().lower() not in {
        "local", "development", "demo", "staging", "test"
    }:
        from app.domain.errors.errors import AuthenticatorNotConfiguredError
        raise AuthenticatorNotConfiguredError("staff authenticator is not configured")
    from app.adapter.staff_auth import DemoStaffAuthenticator
    return DemoStaffAuthenticator()


def get_admin_runtime_settings() -> AdminSettings:
    return admin_settings


def get_staff_identity_repository():
    from app.db.engine import get_engine
    from app.db.staff_identity_repository import SqlAlchemyStaffIdentityRepository
    return SqlAlchemyStaffIdentityRepository(get_engine())


def get_staff_authenticator_http(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    service_id: str | None = Header(default=None, alias="X-Service-ID"),
    runtime_settings: AdminSettings = Depends(get_admin_runtime_settings),
    repository=Depends(get_staff_identity_repository),
) -> StaffAuthenticator:
    environment = runtime_settings.app_env.strip().lower()
    if environment in {"local", "development", "demo", "staging", "test"}:
        from app.adapter.staff_auth import DemoStaffAuthenticator
        return DemoStaffAuthenticator(service_id=service_id or "demo-service")
    if credentials is None:
        raise HTTPException(status_code=401, detail={"error": "authorization_required"})
    if not runtime_settings.admin_oidc_enabled:
        raise HTTPException(status_code=503, detail={"error": "staff_auth_unavailable"})
    try:
        from app.adapter.oidc_staff_auth import OidcStaffAuthenticator, OidcTokenValidator
        from app.services.http_client import get_client
        algorithms = tuple(
            item.strip() for item in runtime_settings.admin_oidc_algorithms.split(",")
            if item.strip()
        )
        return OidcStaffAuthenticator(
            token=credentials.credentials,
            requested_service_id=service_id,
            validator=OidcTokenValidator(
                issuer=runtime_settings.admin_oidc_issuer or "",
                audience=runtime_settings.admin_oidc_audience or "",
                jwks_url=runtime_settings.admin_oidc_jwks_url or "",
                algorithms=algorithms,
                client=get_client(),
            ),
            repository=repository,
        )
    except (StaffAuthenticationError, ValueError):
        raise HTTPException(status_code=503, detail={"error": "staff_auth_unavailable"})


async def get_current_staff(
    authenticator: StaffAuthenticator = Depends(get_staff_authenticator_http),
) -> AuthenticatedStaff:
    try:
        staff = await authenticator.get_current_staff()
        if not staff.active:
            raise InactiveStaffError("staff is inactive")
        return staff
    except InactiveStaffError:
        raise HTTPException(status_code=403, detail={"error": "inactive_staff"})
    except (UnknownStaffIdentityError, StaffServiceScopeError):
        raise HTTPException(status_code=403, detail={"error": "forbidden"})
    except InvalidStaffTokenError:
        raise HTTPException(status_code=401, detail={"error": "invalid_token"})
    except StaffUnavailableError:
        raise HTTPException(status_code=503, detail={"error": "staff_auth_unavailable"})
    except StaffAuthenticationError:
        raise HTTPException(status_code=401, detail={"error": "invalid_token"})


async def require_admin_viewer(
    staff: AuthenticatedStaff = Depends(get_current_staff),
) -> AuthenticatedStaff:
    return staff


async def require_admin_operator(
    staff: AuthenticatedStaff = Depends(get_current_staff),
) -> AuthenticatedStaff:
    if staff.role not in {StaffRole.OPERATOR, StaffRole.SENDER, StaffRole.ADMIN}:
        raise HTTPException(status_code=403, detail={"error": "forbidden"})
    return staff


async def require_admin_role(
    staff: AuthenticatedStaff = Depends(get_current_staff),
) -> AuthenticatedStaff:
    if staff.role is not StaffRole.ADMIN:
        raise HTTPException(status_code=403, detail={"error": "forbidden"})
    return staff

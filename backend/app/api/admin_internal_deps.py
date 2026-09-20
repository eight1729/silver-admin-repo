"""Dedicated incoming LINE-to-Admin credential and configured scope boundary."""

import hmac
import re

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.adapter.admin_scope import ConfiguredOrganizationServiceScopeResolver
from app.adapter.current_db_external_business import CurrentDbExternalBusinessGateway
from app.db.engine import get_engine
from app.application.admin_internal_service import AdminInternalService
from app.domain.errors.errors import ExternalBusinessNotConfiguredError
from app.domain.ports.organization_service_scope import OrganizationServiceScopeNotConfiguredError

_bearer = HTTPBearer(auto_error=False, scheme_name="LineToAdminBearer")
_token_pattern = re.compile(r"[A-Za-z0-9._~+/-]+=*")


def require_admin_internal_bearer(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    settings = getattr(request.app.state, "admin_runtime_settings", None)
    secret = getattr(settings, "admin_internal_api_bearer_token", None)
    expected = secret.get_secret_value() if secret is not None else ""
    if not _token_pattern.fullmatch(expected):
        raise HTTPException(503, detail={"error": "authentication_unavailable"})
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not hmac.compare_digest(credentials.credentials.encode(), expected.encode())
    ):
        raise HTTPException(
            401, detail={"error": "authentication_failed"},
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_admin_internal_service(
    request: Request, _auth: None = Depends(require_admin_internal_bearer),
) -> AdminInternalService:
    settings = request.app.state.admin_runtime_settings
    try:
        scopes = ConfiguredOrganizationServiceScopeResolver(settings.admin_internal_api_scopes)
    except (ValueError, TypeError):
        raise OrganizationServiceScopeNotConfiguredError("business scope is not configured") from None
    gateway = getattr(request.app.state, "admin_internal_business_gateway", None)
    if gateway is None:
        centers = getattr(settings, "current_db_business_centers", {})
        if not centers:
            raise ExternalBusinessNotConfiguredError("Current DB business scopes are not configured")
        gateway = CurrentDbExternalBusinessGateway(get_engine(), centers)
    return AdminInternalService(gateway, scopes)

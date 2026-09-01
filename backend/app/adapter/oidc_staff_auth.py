from typing import Any

import httpx
import jwt

from app.domain.enums.enums import StaffRole
from app.domain.errors.errors import (
    InactiveStaffError,
    InvalidStaffTokenError,
    StaffServiceScopeError,
    UnknownStaffIdentityError,
)
from app.domain.models.staff import AuthenticatedStaff
from app.domain.ports.staff_auth import StaffIdentityRepository


class OidcTokenValidator:
    _SAFE_ALGORITHMS = {
        "RS256", "RS384", "RS512", "PS256", "PS384", "PS512",
        "ES256", "ES384", "ES512", "EdDSA",
    }
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        algorithms: tuple[str, ...],
        client: httpx.AsyncClient,
    ) -> None:
        if not issuer or not audience or not jwks_url or not algorithms:
            raise ValueError("OIDC validation configuration is incomplete")
        if any(item not in self._SAFE_ALGORITHMS for item in algorithms):
            raise ValueError("unsafe OIDC algorithm")
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._jwks_url = jwks_url
        self._algorithms = algorithms
        self._client = client

    async def validate(self, token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
            algorithm = header.get("alg")
            key_id = header.get("kid")
            if algorithm not in self._algorithms or not key_id:
                raise InvalidStaffTokenError("invalid staff token")
            response = await self._client.get(
                self._jwks_url, headers={"Accept": "application/json"}
            )
            response.raise_for_status()
            keys = response.json().get("keys", [])
            jwk = next((item for item in keys if item.get("kid") == key_id), None)
            if jwk is None:
                raise InvalidStaffTokenError("invalid staff token")
            signing_key = jwt.PyJWK.from_dict(jwk, algorithm=algorithm).key
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=list(self._algorithms),
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "require": ["exp", "iss", "sub", "aud"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
            if not isinstance(claims.get("sub"), str) or not claims["sub"].strip():
                raise InvalidStaffTokenError("invalid staff token")
            return claims
        except InvalidStaffTokenError:
            raise
        except (
            jwt.PyJWTError, httpx.HTTPError, ValueError, TypeError, KeyError,
            AttributeError,
        ):
            raise InvalidStaffTokenError("invalid staff token") from None


class OidcStaffAuthenticator:
    def __init__(
        self,
        *,
        token: str,
        requested_service_id: str | None,
        validator: OidcTokenValidator,
        repository: StaffIdentityRepository,
    ) -> None:
        self._token = token
        self._requested_service_id = (
            requested_service_id.strip() if requested_service_id else None
        )
        self._validator = validator
        self._repository = repository

    async def get_current_staff(self) -> AuthenticatedStaff:
        claims = await self._validator.validate(self._token)
        issuer = str(claims["iss"]).rstrip("/")
        subject = str(claims["sub"])
        resolved = await self._repository.find_by_oidc_identity(issuer, subject)
        if resolved is None:
            raise UnknownStaffIdentityError("staff identity is not registered")
        identity, permissions = resolved
        if not identity.active:
            raise InactiveStaffError("staff is inactive")
        selected = self._select_permission(permissions)
        role = StaffRole.OPERATOR if selected.role is StaffRole.SENDER else selected.role
        return AuthenticatedStaff(
            staff_id=str(identity.staff_id),
            display_name=identity.display_name or str(identity.staff_id),
            role=role,
            service_id=selected.service_id,
            active=True,
        )

    def _select_permission(self, permissions):
        if self._requested_service_id:
            match = next(
                (
                    item
                    for item in permissions
                    if item.service_id == self._requested_service_id
                ),
                None,
            )
            if match is None:
                raise StaffServiceScopeError("service scope is not permitted")
            return match
        if len(permissions) != 1:
            raise StaffServiceScopeError("service scope must be selected")
        return permissions[0]

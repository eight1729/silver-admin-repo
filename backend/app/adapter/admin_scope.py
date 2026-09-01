from collections.abc import Mapping

from app.contracts.admin_line_internal_v1 import ServiceOrganizationScope
from app.domain.ports.organization_service_scope import (
    OrganizationServiceScopeNotConfiguredError,
)


class ConfiguredOrganizationServiceScopeResolver:
    """Exact service-to-organization lookup with no inferred fallback."""

    def __init__(self, organizations_by_service: Mapping[str, str]) -> None:
        self._scopes: dict[str, ServiceOrganizationScope] = {}
        for service_id, organization_id in organizations_by_service.items():
            if (
                not isinstance(service_id, str)
                or not service_id
                or service_id != service_id.strip()
                or not isinstance(organization_id, str)
                or not organization_id
                or organization_id != organization_id.strip()
            ):
                raise ValueError("configured business scope identifiers are invalid")
            scope = ServiceOrganizationScope(
                organization_id=organization_id,
                service_id=service_id,
            )
            self._scopes[scope.service_id] = scope

    @property
    def scopes(self) -> tuple[ServiceOrganizationScope, ...]:
        return tuple(self._scopes.values())

    def resolve(self, service_id: str) -> ServiceOrganizationScope:
        if not isinstance(service_id, str) or service_id != service_id.strip():
            raise OrganizationServiceScopeNotConfiguredError(
                "business scope is not configured"
            )
        try:
            return self._scopes[service_id]
        except KeyError as error:
            raise OrganizationServiceScopeNotConfiguredError(
                "business scope is not configured"
            ) from error

from typing import Protocol

from app.contracts.admin_line_internal_v1 import ServiceOrganizationScope


class OrganizationServiceScopeNotConfiguredError(LookupError):
    pass


class OrganizationServiceScopeResolver(Protocol):
    """Resolve a selected Admin service to its canonical business scope."""

    def resolve(self, service_id: str) -> ServiceOrganizationScope: ...

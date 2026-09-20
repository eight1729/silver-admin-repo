"""Scoped business reads for the Admin-owned S2S boundary."""

from app.domain.errors.errors import ExternalSystemUnavailableError
from app.domain.models.external_business import (
    ExternalJobDetail, ExternalJobSummary, ExternalMemberSummary,
    MemberVerificationInput, MemberVerificationResult,
)
from app.domain.ports.external_business import ExternalBusinessGateway
from app.domain.ports.organization_service_scope import (
    OrganizationServiceScopeNotConfiguredError, OrganizationServiceScopeResolver,
)


class AdminInternalService:
    def __init__(
        self, gateway: ExternalBusinessGateway, scopes: OrganizationServiceScopeResolver,
    ) -> None:
        self._gateway = gateway
        self._scopes = scopes

    def _organization(self, service_id: str) -> str:
        scope = self._scopes.resolve(service_id)
        if scope.service_id != service_id or not scope.organization_id:
            raise OrganizationServiceScopeNotConfiguredError("business scope is not configured")
        return scope.organization_id

    async def verify_member(
        self, service_id: str, verification: MemberVerificationInput,
    ) -> MemberVerificationResult:
        return await self._gateway.verify_member(
            external_organization_id=self._organization(service_id), verification=verification,
        )

    async def get_member_summary(self, service_id: str, member_id: str) -> ExternalMemberSummary:
        result = await self._gateway.get_member_summary(
            external_organization_id=self._organization(service_id), external_member_id=member_id,
        )
        if result.external_member_id != member_id:
            raise ExternalSystemUnavailableError("inconsistent member response")
        return result

    async def list_recommended_jobs(self, service_id: str, member_id: str) -> list[ExternalJobSummary]:
        return await self._gateway.list_recommended_jobs(
            external_organization_id=self._organization(service_id), external_member_id=member_id,
        )

    async def get_job_detail(self, service_id: str, job_id: str) -> ExternalJobDetail:
        result = await self._gateway.get_job_detail(
            external_organization_id=self._organization(service_id), external_job_id=job_id,
        )
        if result.external_job_id != job_id:
            raise ExternalSystemUnavailableError("inconsistent job response")
        return result

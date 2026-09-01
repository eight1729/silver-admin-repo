"""Thin application facade for the local-demo Admin API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from uuid import UUID

from app.application.notification_service import (
    CreateNotificationOperationCommand,
    NotificationOperationResult,
    NotificationService,
    NotificationTargetInput,
    OperationNotSendableError,
    ReplaceNotificationTargetsCommand,
    ResetDemoDataResult,
    SendNotificationOperationCommand,
    UpdateNotificationDraftCommand,
    ValidateNotificationOperationCommand,
)
from app.domain.enums.enums import NotificationEligibilityReason, OperationStatus
from app.domain.enums.notification_type import NotificationType
from app.domain.errors.errors import (
    ExternalBusinessNotConfiguredError,
    ExternalJobNotFoundError,
)
from app.domain.errors.admin_notification_repository import (
    OperationNotFoundError,
    ServiceScopeViolationError,
)
from app.domain.models.external_business import (
    CandidateMember,
    ExternalJobDetail,
    ExternalJobSummary,
    JobSearchQuery,
)
from app.domain.ports.external_business import ExternalBusinessGateway
from app.domain.ports.organization_service_scope import (
    OrganizationServiceScopeResolver,
    OrganizationServiceScopeNotConfiguredError,
)
from app.contracts.admin_line_internal_v1 import (
    LiffDeepLinkRequest,
    LinkageStatusBatchRequest,
    ServiceOrganizationScope,
)


class AdminResourceNotFoundError(Exception):
    pass


class AdminDependencyUnavailableError(Exception):
    pass


class AdminExternalSystemUnavailableError(AdminDependencyUnavailableError):
    """Safe Admin boundary signal for an unavailable external dependency."""


def normalize_admin_exception(exc: Exception) -> Exception:
    """Hide local implementation exceptions from the HTTP layer."""
    if isinstance(
        exc,
        (
            OperationNotFoundError,
            ServiceScopeViolationError,
            OrganizationServiceScopeNotConfiguredError,
        ),
    ):
        return AdminResourceNotFoundError("admin resource was not found")
    if isinstance(exc, ExternalBusinessNotConfiguredError):
        return AdminDependencyUnavailableError("admin dependency is unavailable")
    return exc


@dataclass(frozen=True, slots=True)
class AdminCandidate:
    member_id: str
    display_name: str
    line_linked: bool
    eligible: bool
    reason: str | None
    selected: bool = False
    line_subject: str | None = None
    preference_summary: str | None = None


class AdminApplicationService:
    def __init__(
        self,
        *,
        notification_service: NotificationService,
        external_business_gateway: ExternalBusinessGateway,
        demo_service_id: str | None,
        line_linked_member_ids: frozenset[str],
        reset_callbacks: tuple[Callable[[], None], ...] = (),
        expose_line_subjects: bool = True,
        line_internal_client=None,
        organization_id_resolver: Callable[[str], str] | None = None,
        external_business_organization_id_resolver: Callable[[str], str] | None = None,
        scope_resolver: OrganizationServiceScopeResolver | None = None,
        legacy_notification_link_resolver: Callable[[str], str] | None = None,
    ) -> None:
        self.notification_service = notification_service
        self._external = external_business_gateway
        self._demo_service_id = demo_service_id
        self._line_linked = line_linked_member_ids
        self._reset_callbacks = reset_callbacks
        self._expose_line_subjects = expose_line_subjects
        self._line_internal_client = line_internal_client
        self._organization_id_resolver = organization_id_resolver
        self._external_business_organization_id_resolver = (
            external_business_organization_id_resolver
            or organization_id_resolver
        )
        self._scope_resolver = scope_resolver
        self._legacy_notification_link_resolver = legacy_notification_link_resolver

    def _check_service(self, service_id: str) -> None:
        if self._scope_resolver is not None:
            self._scope_resolver.resolve(service_id)
            return
        if service_id != self._demo_service_id:
            raise ExternalJobNotFoundError("resource is outside demo service scope")

    def _business_scope(self, service_id: str) -> ServiceOrganizationScope:
        if self._scope_resolver is not None:
            return self._scope_resolver.resolve(service_id)
        if self._external_business_organization_id_resolver is None:
            raise AdminDependencyUnavailableError(
                "business organization scope is unavailable"
            )
        organization_id = self._external_business_organization_id_resolver(
            service_id
        )
        if (
            not isinstance(organization_id, str)
            or not organization_id
            or organization_id != organization_id.strip()
        ):
            raise OrganizationServiceScopeNotConfiguredError(
                "business scope is not configured"
            )
        return ServiceOrganizationScope(
            organization_id=organization_id,
            service_id=service_id,
        )

    async def list_jobs(self, service_id: str) -> tuple[ExternalJobSummary, ...]:
        scope = self._business_scope(service_id)
        result = await self._external.search_jobs(
            external_organization_id=scope.organization_id, query=JobSearchQuery()
        )
        return tuple(result.items)

    async def get_job(self, service_id: str, job_id: str) -> ExternalJobDetail:
        scope = self._business_scope(service_id)
        job = await self._external.get_job_detail(
            external_organization_id=scope.organization_id, external_job_id=job_id
        )
        if job.external_job_id != job_id:
            raise ExternalJobNotFoundError("job was not found")
        return job

    async def list_candidates(
        self, service_id: str, job_id: str
    ) -> tuple[AdminCandidate, ...]:
        await self.get_job(service_id, job_id)
        scope = self._business_scope(service_id)
        candidates = await self._external.list_candidate_members(
            external_organization_id=scope.organization_id, external_job_id=job_id
        )
        linkage = None
        if self._line_internal_client is not None:
            scope = self._line_scope(service_id)
            response = await self._line_internal_client.batch_get_linkages(
                LinkageStatusBatchRequest(
                    scope=scope,
                    external_member_ids=tuple(
                        item.external_member_id for item in candidates
                    ),
                )
            )
            linkage = {item.external_member_id: item.line_linked for item in response.items}
        return tuple(
            self._candidate(
                item,
                None if linkage is None else linkage.get(item.external_member_id, False),
            )
            for item in candidates
        )

    def _candidate(self, item: CandidateMember, line_linked: bool | None = None) -> AdminCandidate:
        return AdminCandidate(
            member_id=item.external_member_id,
            display_name=item.display_label or f"デモ会員 {item.external_member_id}",
            line_linked=(
                line_linked if line_linked is not None else (
                    item.external_member_id in self._line_linked
                    and item.line_subject is not None
                )
            ),
            eligible=item.eligible,
            reason=(item.reason_codes[0] if item.reason_codes else None),
            line_subject=(
                None if self._line_internal_client is not None else item.line_subject
            ),
            preference_summary=item.preference_summary,
        )

    def _line_scope(self, service_id: str) -> ServiceOrganizationScope:
        if self._scope_resolver is not None:
            return self._scope_resolver.resolve(service_id)
        if self._organization_id_resolver is None:
            raise AdminDependencyUnavailableError("LINE organization scope is unavailable")
        organization_id = self._organization_id_resolver(service_id)
        return ServiceOrganizationScope(
            organization_id=organization_id, service_id=service_id
        )

    async def resolve_notification_link(self, service_id: str, job_id: str) -> str:
        if self._line_internal_client is not None:
            result = await self._line_internal_client.resolve_deep_link(
                LiffDeepLinkRequest(scope=self._line_scope(service_id), job_id=job_id)
            )
            return str(result.canonical_deep_link)
        if self._legacy_notification_link_resolver is not None:
            return self._legacy_notification_link_resolver(job_id)
        raise AdminDependencyUnavailableError("LINE deep-link service is unavailable")

    async def create_operation(
        self,
        *,
        service_id: str,
        staff_id: str,
        job_id: str,
        notification_type: NotificationType,
        greeting: str,
        introduction: str,
        note: str,
    ):
        job = await self.get_job(service_id, job_id)
        return await self.notification_service.create_operation(
            CreateNotificationOperationCommand(
                service_id=service_id,
                job_id=job_id,
                job_version=job.version,
                notification_type=notification_type,
                greeting=greeting,
                introduction=introduction,
                note=note,
                created_by_staff_id=staff_id,
            )
        )

    async def get_operation(
        self, service_id: str, operation_id: UUID
    ) -> NotificationOperationResult:
        return await self.notification_service.get_operation(service_id, operation_id)

    async def update_operation(
        self,
        *,
        service_id: str,
        operation_id: UUID,
        staff_id: str,
        greeting: str,
        introduction: str,
        note: str,
    ):
        return await self.notification_service.update_draft(
            UpdateNotificationDraftCommand(
                service_id, operation_id, greeting, introduction, note, staff_id
            )
        )

    async def replace_targets(
        self,
        *,
        service_id: str,
        operation_id: UUID,
        selected_member_ids: tuple[str, ...],
        staff_id: str,
    ) -> NotificationOperationResult:
        if len(set(selected_member_ids)) != len(selected_member_ids):
            raise ValueError("duplicate selected member")
        operation = (await self.notification_service.get_operation(
            service_id, operation_id
        )).operation
        candidates = await self.list_candidates(service_id, operation.job_id)
        by_id = {item.member_id: item for item in candidates}
        if any(member_id not in by_id for member_id in selected_member_ids):
            raise ValueError("selected member is not a job candidate")
        selected = set(selected_member_ids)
        targets = tuple(
            NotificationTargetInput(
                member_id=item.member_id,
                selected=item.member_id in selected,
                line_linked=item.line_linked,
                eligibility=(
                    None if item.eligible else NotificationEligibilityReason.UNKNOWN
                ),
                reason=item.reason,
                line_subject=item.line_subject,
            )
            for item in candidates
        )
        return await self.notification_service.replace_targets(
            ReplaceNotificationTargetsCommand(
                service_id, operation_id, targets, staff_id
            )
        )

    async def validate(
        self, *, service_id: str, operation_id: UUID, staff_id: str, request_id: str
    ):
        result = await self.notification_service.validate_operation(
            ValidateNotificationOperationCommand(
                service_id, operation_id, staff_id, request_id
            )
        )
        operation = (await self.notification_service.get_operation(
            service_id, operation_id
        )).operation
        if operation.status is OperationStatus.BLOCKED_EXTERNAL_SYSTEM:
            raise AdminExternalSystemUnavailableError("external validation unavailable")
        return result

    async def send(
        self, *, service_id: str, operation_id: UUID, staff_id: str, request_id: str
    ):
        try:
            return await self.notification_service.send_operation(
                SendNotificationOperationCommand(
                    service_id, operation_id, staff_id, request_id
                )
            )
        except OperationNotSendableError:
            operation = (await self.notification_service.get_operation(
                service_id, operation_id
            )).operation
            if operation.status is OperationStatus.BLOCKED_EXTERNAL_SYSTEM:
                raise AdminExternalSystemUnavailableError(
                    "external validation unavailable"
                ) from None
            raise

    async def list_deliveries(self, service_id: str, operation_id: UUID):
        await self.notification_service.get_operation(service_id, operation_id)
        return await self.notification_service.list_deliveries(service_id, operation_id)

    async def reset(self, service_id: str) -> ResetDemoDataResult:
        self._check_service(service_id)
        result = await self.notification_service.reset_demo_data()
        for callback in self._reset_callbacks:
            callback()
        return result

"""Thin application facade for the local-demo Admin API."""

from __future__ import annotations

from app.core.jobs_diagnostics import jobs_point, jobs_failure
from app.application.automatic_selection import automatic_context, confirmation_identity, select_automatic_members

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from app.application.notification_service import (
    CreateNotificationOperationCommand,
    NotificationOperationResult,
    NotificationService,
    NotificationTargetInput,
    OperationNotSendableError,
    ReplaceNotificationTargetsCommand,
    SendNotificationOperationCommand,
    UpdateNotificationDraftCommand,
    ValidateNotificationOperationCommand,
)
from app.domain.enums.enums import NotificationEligibilityReason, OperationStatus
from app.domain.enums.notification_type import NotificationType
from app.domain.errors.errors import (
    ExternalBusinessNotConfiguredError,
    ExternalJobNotFoundError,
    ExternalMemberNotFoundError,
    ExternalSystemUnavailableError,
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
from app.adapter.line_internal_api import LineInternalApiClientError
from app.domain.ports.organization_service_scope import (
    OrganizationServiceScopeResolver,
    OrganizationServiceScopeNotConfiguredError,
)
from app.contracts.admin_line_internal_v1 import (
    LiffDeepLinkRequest,
    LinkageStatusBatchRequest,
    LinkageStatusBatchResponse,
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
    member_number: str | None = None
    recommendation_level: int | None = None


JOB_PAGE_SIZE = 200
MAX_JOB_PAGES = 100


class AdminApplicationService:
    def __init__(
        self,
        *,
        notification_service: NotificationService,
        external_business_gateway: ExternalBusinessGateway,
        demo_service_id: str | None,
        line_linked_member_ids: frozenset[str],
        expose_line_subjects: bool = True,
        line_internal_client=None,
        organization_id_resolver: Callable[[str], str] | None = None,
        external_business_organization_id_resolver: Callable[[str], str] | None = None,
        scope_resolver: OrganizationServiceScopeResolver | None = None,
    ) -> None:
        self.notification_service = notification_service
        self._external = external_business_gateway
        self._demo_service_id = demo_service_id
        self._line_linked = line_linked_member_ids
        self._expose_line_subjects = expose_line_subjects
        self._line_internal_client = line_internal_client
        self._organization_id_resolver = organization_id_resolver
        self._external_business_organization_id_resolver = (
            external_business_organization_id_resolver
            or organization_id_resolver
        )
        self._scope_resolver = scope_resolver

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
        stage = "list_jobs_scope"
        jobs_point("admin_application", "list_jobs_start")
        try:
            scope = self._business_scope(service_id)
            stage = "list_jobs_provider"
            # Collect the complete provider result before ordering. Never expose a
            # successful partial list when pagination is inconsistent or bounded out.
            collected = []
            seen = set()
            expected_total = None
            for page in range(1, MAX_JOB_PAGES + 1):
                result = await self._external.search_jobs(
                    external_organization_id=scope.organization_id,
                    query=JobSearchQuery(page=page, page_size=JOB_PAGE_SIZE),
                )
                if (result.page != page or result.page_size != JOB_PAGE_SIZE
                        or len(result.items) > JOB_PAGE_SIZE):
                    raise AdminDependencyUnavailableError("Job pagination is inconsistent")
                if result.total_count is not None:
                    if result.total_count < 0 or (expected_total is not None
                            and expected_total != result.total_count):
                        raise AdminDependencyUnavailableError("Job pagination changed")
                    expected_total = result.total_count
                for item in result.items:
                    if item.external_job_id in seen:
                        raise AdminDependencyUnavailableError("Job pagination repeated an identity")
                    if item.created_at is not None and (
                            not isinstance(item.created_at, datetime) or item.created_at.utcoffset() is None):
                        raise AdminDependencyUnavailableError("Job registration date is invalid")
                    seen.add(item.external_job_id)
                    collected.append(item)
                if expected_total is not None and len(collected) > expected_total:
                    raise AdminDependencyUnavailableError("Job pagination is inconsistent")
                if not result.has_next:
                    if expected_total is not None and len(collected) != expected_total:
                        raise AdminDependencyUnavailableError("Job pagination is incomplete")
                    break
                if not result.items or (expected_total is not None and len(collected) >= expected_total):
                    raise AdminDependencyUnavailableError("Job pagination made no progress")
            else:
                raise AdminDependencyUnavailableError("Job pagination limit exceeded")
            stage = "list_jobs_response"
            # Stable identity tie-break; unknown dates remain last, without fallback.
            collected.sort(key=lambda item: item.external_job_id)
            collected.sort(key=lambda item: (
                item.created_at is not None,
                item.created_at or datetime.min.replace(tzinfo=timezone.utc),
            ), reverse=True)
            items = tuple(collected)
            jobs_point("admin_application", "list_jobs_complete")
            return items
        except Exception as exc:
            jobs_failure("admin_application", stage, exc)
            raise

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
            linkage = await self._lookup_linkages(
                scope, (item.external_member_id for item in candidates)
            )
        if len({item.external_member_id for item in candidates}) != len(candidates):
            raise AdminDependencyUnavailableError("duplicate candidate identities")
        return tuple(
            self._candidate(
                item,
                None if linkage is None else linkage[item.external_member_id],
            )
            for item in candidates
        )

    async def confirmed_linkages(self, service_id, member_ids):
        if self._line_internal_client is None:
            raise ExternalSystemUnavailableError("LINE linkage is unavailable")
        try:
            return await self._lookup_linkages(self._line_scope(service_id), member_ids)
        except AdminDependencyUnavailableError:
            raise ExternalSystemUnavailableError("LINE linkage is unavailable") from None

    async def automatic_selection(self, service_id, job_id):
        job = await self.get_job(service_id, job_id)
        if job.status.value != "published":
            raise ValueError("only published jobs can be selected")
        if self._line_internal_client is None:
            raise AdminDependencyUnavailableError("canonical LINE linkage is required")
        candidates = await self.list_candidates(service_id, job_id)
        try:
            selected = select_automatic_members(candidates)
        except ValueError:
            raise AdminDependencyUnavailableError("automatic selection data is incomplete") from None
        return {"selected_member_ids": selected,
                "reason": None if selected else "評価5・LINE連携済みの選択可能な会員がいません。未評価は対象外です。"}

    async def confirmation(self, service_id, operation_id):
        result = await self.get_operation(service_id, operation_id)
        operation, targets = result.operation, result.targets
        context = automatic_context(operation)
        if context is None:
            raise ValueError("automatic operation required")
        snapshot = operation.validation_snapshot or {}
        rows = {i["member_id"]: i for i in snapshot.get("target_results", ()) if i["selected"]}
        scope = self._business_scope(service_id)
        items = []
        for target in targets:
            if not target.selected:
                continue
            row = rows.get(target.member_id)
            member = None
            try:
                member = await self._external.get_member_summary(external_organization_id=scope.organization_id,
                                                               external_member_id=target.member_id)
            except ExternalMemberNotFoundError:
                pass  # Unknown attributes remain explicit; never invent identity data.
            if member is not None and member.external_member_id != target.member_id:
                raise AdminDependencyUnavailableError("member identity mismatch")
            disposition = row["delivery_disposition"] if row else "block"
            items.append(dict(member_id=target.member_id, member_number=member.member_number if member else None,
                display_name=member.display_label if member else None,
                mobile_phone_last4=member.mobile_phone_last4 if member else None,
                disposition=disposition, reason=row["reason"] if row else snapshot.get("blocking_reason") or "revalidation_required"))
        # Reject a concurrent edit/validation while resolving display attributes.
        current = await self.get_operation(service_id, operation_id)
        token = confirmation_identity(operation, targets)
        if token != confirmation_identity(current.operation, current.targets):
            raise OperationNotSendableError("confirmation changed")
        sendable = sum(i["disposition"] == "send" for i in items)
        valid = (operation.status.value == "ready" and operation.validated_at is not None
                 and snapshot.get("can_proceed") is True and not snapshot.get("requires_staff_reconfirmation")
                 and set(rows) == {t.member_id for t in targets if t.selected} and sendable > 0
                 and operation.send_requested_at is None)
        limit = self.notification_service._selected_recipient_limit
        return dict(operation_id=operation_id, initial_count=context["initial_count"], selected_count=len(items),
            sendable_count=sendable, excluded_count=len(items)-sendable,
            message=dict(greeting=operation.message.greeting, introduction=operation.message.introduction, note=operation.message.note),
            targets=items, confirmation_token=token if valid else None,
            requires_revalidation=not valid, selected_recipient_limit=limit,
            can_send=valid and (limit is None or len(items) <= limit))

    async def _lookup_linkages(self, scope, member_ids):
        ids = tuple(dict.fromkeys(member_ids))
        lookup = {}
        try:
            for offset in range(0, len(ids), 500):
                chunk = ids[offset:offset + 500]
                response = LinkageStatusBatchResponse.model_validate(
                    await self._line_internal_client.batch_get_linkages(
                        LinkageStatusBatchRequest(scope=scope, external_member_ids=chunk)
                    )
                )
                returned = tuple(item.external_member_id for item in response.items)
                if len(returned) != len(chunk) or set(returned) != set(chunk):
                    raise ValueError("linkage response identity mismatch")
                lookup.update((item.external_member_id, item.line_linked) for item in response.items)
        except (LineInternalApiClientError, ValueError):
            raise AdminDependencyUnavailableError("LINE linkage lookup unavailable") from None
        return lookup

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
            member_number=item.member_number,
            recommendation_level=item.recommendation_level,
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
        automatic_selection: bool = False,
    ):
        job = await self.get_job(service_id, job_id)
        if automatic_selection:
            selection = await self.automatic_selection(service_id, job_id)
            if not selection["selected_member_ids"]:
                raise ValueError("no automatic targets")
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
                automatic_selection=automatic_selection,
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
        reinclude_member_ids: tuple[str, ...] = (),
    ) -> NotificationOperationResult:
        if len(set(selected_member_ids)) != len(selected_member_ids):
            raise ValueError("duplicate selected member")
        operation = (await self.notification_service.get_operation(
            service_id, operation_id
        )).operation
        context = automatic_context(operation)
        if context is not None and not context["initialized"]:
            authoritative = await self.automatic_selection(service_id, operation.job_id)
            if set(selected_member_ids) != set(authoritative["selected_member_ids"]):
                raise OperationNotSendableError("automatic selection changed; select again")
        candidates = await self.list_candidates(service_id, operation.job_id)
        by_id = {item.member_id: item for item in candidates}
        if context is not None:
            previous = (await self.get_operation(service_id, operation_id)).targets
            for target in previous:
                if target.selected and target.member_id in selected_member_ids and target.member_id not in by_id:
                    by_id[target.member_id] = AdminCandidate(target.member_id, "取得不可", False, False, "member_no_longer_candidate")
            candidates = tuple(by_id.values())
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
                service_id, operation_id, targets, staff_id, reinclude_member_ids
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
        if (automatic_context(operation) is not None and result.requires_staff_reconfirmation
                and result.job_valid and result.version_matches and result.eligible_count > 0 and result.invalid_count == 0):
            result = await self.notification_service.validate_operation(
                ValidateNotificationOperationCommand(service_id, operation_id, staff_id, request_id))
        return result

    async def send(
        self, *, service_id: str, operation_id: UUID, staff_id: str, request_id: str,
        confirmation_token: str | None = None,
    ):
        try:
            return await self.notification_service.send_operation(
                SendNotificationOperationCommand(
                    service_id, operation_id, staff_id, request_id, confirmation_token
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

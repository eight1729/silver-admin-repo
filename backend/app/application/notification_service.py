"""Notification application use cases for the local demo."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging
from typing import Awaitable, Callable
from uuid import UUID, uuid4, uuid5

from app.domain.enums.enums import (
    DeliveryStatus,
    JobStatus,
    NotificationEligibilityReason,
    OperationStatus,
)
from app.domain.enums.notification_type import NotificationType
from app.domain.errors.errors import (
    ExternalJobNotFoundError,
    ExternalSystemUnavailableError,
    LineAuthenticationError,
    LineBadRequestError,
    LineConfigurationError,
    LineRateLimitError,
    LineRecipientUnavailableError,
    LineSendError,
    LineTemporaryError,
    LineUnknownResultError,
    QueueError,
)
from app.domain.models.messaging import JobNotificationMessage
from app.domain.models.notification import NotificationValidationResult
from app.domain.ports.external_business import ExternalBusinessGateway
from app.domain.ports import LineMessageGateway
from app.domain.ports.queue import QueueGateway
from app.domain.errors.admin_notification_repository import (
    SendAttemptAlreadyExistsError,
)
from app.domain.models.admin_notification import (
    NotificationAuditEvent,
    NotificationDeliveryRecord,
    NotificationMessage,
    NotificationOperationRecord,
    NotificationOutboxRecord,
    NotificationTargetRecord,
    freeze_mapping,
)
from app.domain.ports.admin_notification_repository import (
    AdminNotificationRepository,
)

_EDITABLE_STATUSES = frozenset((OperationStatus.DRAFT, OperationStatus.READY))
_logger = logging.getLogger(__name__)

# Statuses that make an operation unsendable before re-validation even starts.
_REJECT_SEND_STATUSES = frozenset(
    (
        OperationStatus.COMPLETED,
        OperationStatus.COMPLETED_WITH_ERRORS,
        OperationStatus.SENDING,
        OperationStatus.CANCELLED,
        OperationStatus.BLOCKED_EXTERNAL_SYSTEM,
    )
)


# ── Application errors ────────────────────────────────────────────────────────


class NotificationApplicationError(Exception):
    """Base class for notification application errors."""


class InvalidNotificationCommandError(NotificationApplicationError):
    pass


class OperationNotEditableError(NotificationApplicationError):
    pass


class EmptyNotificationMessageError(NotificationApplicationError):
    pass


class DuplicateTargetError(NotificationApplicationError):
    pass


class InvalidNotificationTypeError(NotificationApplicationError):
    pass


class OperationNotSendableError(NotificationApplicationError):
    """Raised when send_operation cannot proceed due to operation state."""


# ── Value objects / enums ─────────────────────────────────────────────────────


class ValidationDisposition(str, Enum):
    SEND = "send"
    SKIP = "skip"
    BLOCK = "block"


# ── Commands ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CreateNotificationOperationCommand:
    service_id: str
    job_id: str
    job_version: str | None
    notification_type: NotificationType
    greeting: str
    introduction: str
    note: str
    created_by_staff_id: str


@dataclass(frozen=True, slots=True)
class UpdateNotificationDraftCommand:
    service_id: str
    operation_id: UUID
    greeting: str
    introduction: str
    note: str
    staff_id: str | None = None


@dataclass(frozen=True, slots=True)
class NotificationTargetInput:
    member_id: str
    selected: bool
    line_linked: bool
    eligibility: NotificationEligibilityReason | None
    reason: str | None
    line_subject: str | None = None


@dataclass(frozen=True, slots=True)
class ReplaceNotificationTargetsCommand:
    service_id: str
    operation_id: UUID
    targets: tuple[NotificationTargetInput, ...]
    staff_id: str | None = None


@dataclass(frozen=True, slots=True)
class ValidateNotificationOperationCommand:
    service_id: str
    operation_id: UUID
    staff_id: str
    request_id: str


@dataclass(frozen=True, slots=True)
class SendNotificationOperationCommand:
    """Command to initiate sending a notification operation.

    ``request_id`` is mandatory and serves as a send-idempotency key stored
    on every delivery record created during this send attempt.
    """

    service_id: str
    operation_id: UUID
    staff_id: str
    request_id: str


@dataclass(frozen=True, slots=True)
class ProcessNotificationOperationCommand:
    """Command issued by the queue handler to process pending deliveries."""

    service_id: str
    operation_id: UUID
    request_id: str


# ── Result types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class NotificationOperationResult:
    operation: NotificationOperationRecord
    targets: tuple[NotificationTargetRecord, ...]


@dataclass(frozen=True, slots=True)
class ResetDemoDataResult:
    reset: bool


@dataclass(frozen=True, slots=True)
class NotificationTargetValidationItem:
    member_id: str
    selected: bool
    line_linked: bool
    eligible: bool
    delivery_disposition: ValidationDisposition
    reason: str | None


@dataclass(frozen=True, slots=True)
class NotificationValidationSummary:
    operation_id: UUID
    service_id: str
    job_id: str
    requested_job_version: str | None
    current_job_version: str | None
    job_valid: bool
    version_matches: bool
    message_valid: bool
    selected_target_count: int
    eligible_count: int
    skipped_count: int
    invalid_count: int
    can_proceed: bool
    requires_staff_reconfirmation: bool
    target_results: tuple[NotificationTargetValidationItem, ...]
    validated_at: datetime
    blocking_reason: str | None


# ── Internal helpers ──────────────────────────────────────────────────────────


def _required(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise InvalidNotificationCommandError(f"{field_name} is required")


def _message(greeting: str, introduction: str, note: str) -> NotificationMessage:
    if not all(value and value.strip() for value in (greeting, introduction, note)):
        raise EmptyNotificationMessageError(
            "all notification message sections are required"
        )
    return NotificationMessage(greeting=greeting, introduction=introduction, note=note)


def _message_valid(message: NotificationMessage) -> bool:
    return all(
        value and value.strip()
        for value in (message.greeting, message.introduction, message.note)
    )


def _message_hash(message: NotificationMessage) -> str:
    canonical = json.dumps(
        {
            "greeting": message.greeting,
            "introduction": message.introduction,
            "note": message.note,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validation_snapshot(summary: NotificationValidationSummary) -> dict:
    return {
        "requested_job_version": summary.requested_job_version,
        "current_job_version": summary.current_job_version,
        "job_valid": summary.job_valid,
        "version_matches": summary.version_matches,
        "message_valid": summary.message_valid,
        "selected_target_count": summary.selected_target_count,
        "eligible_count": summary.eligible_count,
        "skipped_count": summary.skipped_count,
        "invalid_count": summary.invalid_count,
        "can_proceed": summary.can_proceed,
        "requires_staff_reconfirmation": summary.requires_staff_reconfirmation,
        "blocking_reason": summary.blocking_reason,
        "validated_at": summary.validated_at.isoformat(),
        "target_results": [
            {
                "member_id": item.member_id,
                "selected": item.selected,
                "line_linked": item.line_linked,
                "eligible": item.eligible,
                "delivery_disposition": item.delivery_disposition.value,
                "reason": item.reason,
            }
            for item in summary.target_results
        ],
    }


def _map_line_exception(exc: LineSendError) -> tuple[DeliveryStatus, str, str]:
    """Map a LineSendError subclass to (delivery_status, error_code, sanitised_message).

    The returned error_message is a generic string; it never contains the raw
    exception text, LINE response body, or any PII.
    """
    if isinstance(exc, (LineAuthenticationError, LineConfigurationError)):
        return (
            DeliveryStatus.FAILED,
            "line_authentication_error",
            "LINE authentication failed",
        )
    if isinstance(exc, LineRecipientUnavailableError):
        return (
            DeliveryStatus.FAILED,
            "recipient_unavailable",
            "LINE recipient unavailable",
        )
    if isinstance(exc, LineRateLimitError):
        return DeliveryStatus.FAILED, "line_rate_limited", "LINE rate limit exceeded"
    if isinstance(exc, LineTemporaryError):
        return DeliveryStatus.FAILED, "line_temporary_error", "LINE temporary error"
    if isinstance(exc, LineBadRequestError):
        return DeliveryStatus.FAILED, "line_bad_request", "LINE bad request error"
    if isinstance(exc, LineUnknownResultError):
        return DeliveryStatus.UNKNOWN, "line_unknown_result", "LINE result unknown"
    # Catch-all for any other LineSendError subclass
    return DeliveryStatus.FAILED, "line_send_error", "LINE send error"


# ── Service ───────────────────────────────────────────────────────────────────


class NotificationService:
    """Coordinate local-demo notification operations."""

    def __init__(
        self,
        *,
        repository: AdminNotificationRepository,
        external_business_gateway: ExternalBusinessGateway | None = None,
        line_sender: LineMessageGateway | None = None,
        queue_gateway: QueueGateway | None = None,
        clock: Callable[[], datetime] | None = None,
        uuid_factory: Callable[[], UUID] | None = None,
        pre_send_guard: (
            Callable[[NotificationOperationResult, NotificationValidationSummary], None]
            | None
        ) = None,
        message_factory: (
            Callable[[NotificationOperationRecord], JobNotificationMessage] | None
        ) = None,
        line_subject_resolver: Callable[[str, str], str] | None = None,
        organization_id_resolver: Callable[[str], str] | None = None,
        external_business_organization_id_resolver: Callable[[str], str] | None = None,
        require_scoped_queue: bool = False,
        persist_line_subjects: bool = True,
        reservation_guard: Callable[[str, int], Awaitable[None]] | None = None,
    ) -> None:
        self._repository = repository
        self._external_business_gateway = external_business_gateway
        self._line_sender = line_sender
        self._queue_gateway = queue_gateway
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._uuid_factory = uuid_factory or uuid4
        self._pre_send_guard = pre_send_guard
        self._message_factory = message_factory
        self._line_subject_resolver = line_subject_resolver
        self._organization_id_resolver = organization_id_resolver
        self._external_business_organization_id_resolver = (
            external_business_organization_id_resolver
            or organization_id_resolver
        )
        self._require_scoped_queue = require_scoped_queue
        self._persist_line_subjects = persist_line_subjects
        self._reservation_guard = reservation_guard

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise InvalidNotificationCommandError(
                "clock must return a timezone-aware datetime"
            )
        return value.astimezone(timezone.utc)

    def _uuid(self) -> UUID:
        value = self._uuid_factory()
        if not isinstance(value, UUID):
            raise InvalidNotificationCommandError("uuid_factory must return UUID")
        return value

    @staticmethod
    def _ensure_editable(operation: NotificationOperationRecord) -> None:
        if operation.send_requested_at is not None or operation.status not in _EDITABLE_STATUSES:
            raise OperationNotEditableError("notification operation is not editable")

    def _audit_event(
        self,
        operation: NotificationOperationRecord,
        event_type: str,
        staff_id: str | None,
        details: dict,
        now: datetime,
    ) -> NotificationAuditEvent:
        return NotificationAuditEvent(
            audit_id=self._uuid(),
            operation_id=operation.operation_id,
            event_type=event_type,
            staff_id=staff_id,
            details=details,
            created_at=now,
        )

    async def _audit(
        self,
        operation: NotificationOperationRecord,
        event_type: str,
        staff_id: str | None,
        details: dict,
        now: datetime,
    ) -> None:
        await self._repository.append_audit_event(
            operation.service_id,
            operation.operation_id,
            self._audit_event(operation, event_type, staff_id, details, now),
        )

    # ── Draft lifecycle ───────────────────────────────────────────────────────

    async def create_operation(
        self, command: CreateNotificationOperationCommand
    ) -> NotificationOperationRecord:
        _required(command.service_id, "service_id")
        _required(command.job_id, "job_id")
        _required(command.created_by_staff_id, "created_by_staff_id")
        if not isinstance(command.notification_type, NotificationType):
            raise InvalidNotificationTypeError("notification_type is invalid")
        message = _message(command.greeting, command.introduction, command.note)
        now = self._now()
        operation = NotificationOperationRecord(
            operation_id=self._uuid(),
            service_id=command.service_id,
            job_id=command.job_id,
            job_version=command.job_version,
            notification_type=command.notification_type,
            message=message,
            status=OperationStatus.DRAFT,
            created_by_staff_id=command.created_by_staff_id,
            created_at=now,
            updated_at=now,
            validated_at=None,
            send_requested_at=None,
            completed_at=None,
            message_version=1,
            message_hash=_message_hash(message),
            validation_snapshot=None,
        )
        stored = await self._repository.create_operation_with_audit(
            operation,
            self._audit_event(
                operation,
                "operation_created",
                command.created_by_staff_id,
                {
                    "notification_type": command.notification_type.value,
                    "job_id": command.job_id,
                },
                now,
            ),
        )
        return stored

    async def get_operation(
        self, service_id: str, operation_id: UUID
    ) -> NotificationOperationResult:
        operation = await self._repository.get_operation(service_id, operation_id)
        return NotificationOperationResult(
            operation, await self._repository.get_targets(service_id, operation_id)
        )

    async def update_draft(
        self, command: UpdateNotificationDraftCommand
    ) -> NotificationOperationRecord:
        operation = await self._repository.get_operation(
            command.service_id, command.operation_id
        )
        self._ensure_editable(operation)
        message = _message(command.greeting, command.introduction, command.note)
        sections = tuple(
            name
            for name in ("greeting", "introduction", "note")
            if getattr(operation.message, name) != getattr(message, name)
        )
        replacement = replace(
            operation,
            message=message,
            message_version=(
                operation.message_version + 1 if sections else operation.message_version
            ),
            message_hash=_message_hash(message),
            status=OperationStatus.DRAFT,
            validated_at=None,
            validation_snapshot=None,
        )
        now = self._now()
        updated = await self._repository.update_operation_with_audit(
            command.service_id,
            command.operation_id,
            replacement,
            self._audit_event(
                operation,
                "draft_updated",
                command.staff_id or operation.created_by_staff_id,
                {"sections": sections},
                now,
            ),
        )
        return updated

    async def replace_targets(
        self, command: ReplaceNotificationTargetsCommand
    ) -> NotificationOperationResult:
        operation = await self._repository.get_operation(
            command.service_id, command.operation_id
        )
        self._ensure_editable(operation)
        member_ids: set[str] = set()
        now = self._now()
        records: list[NotificationTargetRecord] = []
        for target in command.targets:
            _required(target.member_id, "member_id")
            if target.member_id in member_ids:
                raise DuplicateTargetError("duplicate notification target")
            member_ids.add(target.member_id)
            records.append(
                NotificationTargetRecord(
                    command.operation_id,
                    target.member_id,
                    target.selected,
                    target.line_linked,
                    target.eligibility,
                    target.reason,
                    now,
                    now,
                    target.line_subject if self._persist_line_subjects else None,
                )
            )
        updated, targets = await self._repository.replace_targets_with_operation_and_audit(
            command.service_id,
            command.operation_id,
            records,
            replace(
                operation,
                status=OperationStatus.DRAFT,
                validated_at=None,
                validation_snapshot=None,
            ),
            self._audit_event(
                operation,
                "targets_replaced",
                command.staff_id or operation.created_by_staff_id,
                {
                    "selected_count": sum(item.selected for item in records),
                    "total_count": len(records),
                },
                now,
            ),
        )
        return NotificationOperationResult(updated, targets)

    # ── Validation ────────────────────────────────────────────────────────────

    async def validate_operation(
        self, command: ValidateNotificationOperationCommand
    ) -> NotificationValidationSummary:
        _required(command.staff_id, "staff_id")
        _required(command.request_id, "request_id")
        operation = await self._repository.get_operation(
            command.service_id, command.operation_id
        )
        self._ensure_editable(operation)
        targets = await self._repository.get_targets(command.service_id, command.operation_id)
        selected = tuple(target for target in targets if target.selected)
        now = self._now()
        original_status = operation.status
        validating_record = replace(operation, status=OperationStatus.VALIDATING)
        validating = await self._repository.update_operation_with_audit(
            command.service_id,
            command.operation_id,
            validating_record,
            self._audit_event(
                validating_record,
                "validation_started",
                command.staff_id,
                {"request_id": command.request_id},
                now,
            ),
        )

        if not selected:
            summary = self._summary(
                operation,
                None,
                False,
                False,
                _message_valid(operation.message),
                (),
                now,
                "no_selected_targets",
                False,
                False,
            )
            await self._finish_validation(
                operation, summary, OperationStatus.DRAFT, targets, command
            )
            return summary

        gateway = self._external_business_gateway
        if gateway is None:
            await self._restore_status(operation, original_status)
            raise InvalidNotificationCommandError(
                "external business gateway is required"
            )

        if self._external_business_organization_id_resolver is None:
            await self._restore_status(operation, original_status)
            raise OperationNotSendableError(
                "organization identifier cannot be resolved"
            )
        external_organization_id = self._external_business_organization_id_resolver(
            command.service_id
        )
        if (
            not isinstance(external_organization_id, str)
            or not external_organization_id.strip()
        ):
            await self._restore_status(operation, original_status)
            raise OperationNotSendableError(
                "organization identifier cannot be resolved"
            )
        external_organization_id = external_organization_id.strip()

        try:
            job = await gateway.get_job_detail(
                external_organization_id=external_organization_id,
                external_job_id=operation.job_id,
            )
            candidates = await gateway.list_candidate_members(
                external_organization_id=external_organization_id,
                external_job_id=operation.job_id,
            )
            validation = await gateway.validate_notification_targets(
                external_organization_id=external_organization_id,
                external_job_id=operation.job_id,
                expected_job_version=operation.job_version or "",
                external_member_ids=[target.member_id for target in selected],
            )
        except ExternalJobNotFoundError:
            summary = replace(
                self._summary(
                    operation,
                    None,
                    False,
                    False,
                    _message_valid(operation.message),
                    (),
                    now,
                    "job_not_found",
                    False,
                    False,
                ),
                selected_target_count=len(selected),
            )
            await self._finish_validation(
                operation, summary, OperationStatus.READY, targets, command
            )
            return summary
        except ExternalSystemUnavailableError as exc:
            reason = self._external_blocking_reason(exc)
            summary = replace(
                self._summary(
                    operation,
                    None,
                    False,
                    False,
                    _message_valid(operation.message),
                    (),
                    now,
                    reason,
                    False,
                    False,
                ),
                selected_target_count=len(selected),
            )
            blocked = replace(
                operation,
                status=OperationStatus.BLOCKED_EXTERNAL_SYSTEM,
                validated_at=now,
                validation_snapshot=_validation_snapshot(summary),
            )
            await self._repository.update_operation_with_audit(
                command.service_id,
                command.operation_id,
                blocked,
                self._audit_event(
                    blocked,
                    "validation_blocked",
                    command.staff_id,
                    {"blocking_reason": reason, "request_id": command.request_id},
                    now,
                ),
            )
            return summary
        except Exception:
            await self._restore_status(operation, original_status)
            raise

        job_valid = job.status is JobStatus.PUBLISHED and validation.job_eligible
        version_matches = operation.job_version == validation.current_job_version
        blocking_reason = None
        reconfirm = False
        if (
            job.status is not JobStatus.PUBLISHED
            or validation.job_reason_code is NotificationEligibilityReason.JOB_CLOSED
        ):
            blocking_reason = "job_closed"
        elif not version_matches:
            blocking_reason = "job_version_changed"
            reconfirm = True
        elif not validation.job_eligible:
            blocking_reason = (
                validation.job_reason_code.value
                if validation.job_reason_code
                else "job_not_found"
            )

        items, updated_targets, target_difference = self._target_results(
            operation, targets, validation, candidates, now
        )
        reconfirm = reconfirm or target_difference
        sends = sum(
            item.delivery_disposition is ValidationDisposition.SEND for item in items
        )
        blocks = sum(
            item.delivery_disposition is ValidationDisposition.BLOCK for item in items
        )
        skips = sum(
            item.delivery_disposition is ValidationDisposition.SKIP for item in items
        )
        message_valid = _message_valid(operation.message)
        if not message_valid:
            blocking_reason = "empty_notification_message"
        elif sends == 0 and blocking_reason is None:
            blocking_reason = "no_sendable_targets"
        can_proceed = (
            job_valid
            and version_matches
            and message_valid
            and sends > 0
            and blocks == 0
        )
        summary = self._summary(
            operation,
            validation.current_job_version,
            job_valid,
            version_matches,
            message_valid,
            items,
            now,
            blocking_reason,
            can_proceed,
            reconfirm,
        )
        await self._finish_validation(
            operation, summary, OperationStatus.READY, updated_targets, command
        )
        return summary

    def _target_results(self, operation, targets, validation, candidates, now):
        validations = {item.external_member_id: item for item in validation.members}
        candidate_map = {item.external_member_id: item for item in candidates}
        enforce_candidate = (
            operation.notification_type is not NotificationType.CUSTOM_JOB
        )
        results = []
        updated = []
        target_difference = False
        for target in targets:
            reason_code = target.eligibility
            reason = target.reason
            eligible = False
            disposition = ValidationDisposition.SKIP
            if not target.selected:
                reason = "not_selected"
            elif not target.line_linked:
                reason = "line_not_linked"
            else:
                member_validation = validations.get(target.member_id)
                if member_validation is None:
                    reason_code = NotificationEligibilityReason.MEMBER_NOT_FOUND
                    reason = reason_code.value
                    disposition = ValidationDisposition.BLOCK
                    target_difference = True
                elif not member_validation.eligible:
                    reason_code = member_validation.reason_code
                    reason = reason_code.value if reason_code else "member_ineligible"
                    target_difference = True
                elif enforce_candidate and (
                    target.member_id not in candidate_map
                    or not candidate_map[target.member_id].eligible
                ):
                    reason_code = (
                        NotificationEligibilityReason.MEMBER_NO_LONGER_CANDIDATE
                    )
                    reason = reason_code.value
                    target_difference = True
                else:
                    eligible = True
                    reason_code = None
                    reason = None
                    disposition = ValidationDisposition.SEND
            updated_record = replace(
                target, eligibility=reason_code, reason=reason, updated_at=now
            )
            updated.append(updated_record)
            results.append(
                NotificationTargetValidationItem(
                    target.member_id,
                    target.selected,
                    target.line_linked,
                    eligible,
                    disposition,
                    reason,
                )
            )
        return tuple(results), tuple(updated), target_difference

    def _summary(
        self,
        operation,
        current_version,
        job_valid,
        version_matches,
        message_valid,
        items,
        now,
        blocking_reason,
        can_proceed,
        reconfirm,
    ):
        selected_count = sum(item.selected for item in items) if items else 0
        return NotificationValidationSummary(
            operation.operation_id,
            operation.service_id,
            operation.job_id,
            operation.job_version,
            current_version,
            job_valid,
            version_matches,
            message_valid,
            selected_count,
            sum(
                item.delivery_disposition is ValidationDisposition.SEND
                for item in items
            ),
            sum(
                item.delivery_disposition is ValidationDisposition.SKIP
                for item in items
            ),
            sum(
                item.delivery_disposition is ValidationDisposition.BLOCK
                for item in items
            ),
            can_proceed,
            reconfirm,
            tuple(items),
            now,
            blocking_reason,
        )

    async def _finish_validation(self, operation, summary, status, targets, command):
        validated = replace(
            operation,
            status=status,
            validated_at=summary.validated_at,
            validation_snapshot=_validation_snapshot(summary),
        )
        await self._repository.replace_targets_with_operation_and_audit(
            command.service_id,
            command.operation_id,
            targets,
            validated,
            self._audit_event(
                validated,
                "validation_completed",
                command.staff_id,
                {
                    "selected_count": summary.selected_target_count,
                    "eligible_count": summary.eligible_count,
                    "skipped_count": summary.skipped_count,
                    "invalid_count": summary.invalid_count,
                    "version_matches": summary.version_matches,
                    "can_proceed": summary.can_proceed,
                },
                summary.validated_at,
            ),
        )

    async def _restore_status(self, operation, status):
        await self._repository.update_operation(
            operation.service_id,
            operation.operation_id,
            replace(operation, status=status),
        )

    @staticmethod
    def _external_blocking_reason(exc: ExternalSystemUnavailableError) -> str:
        text = str(exc).lower()
        if "rate" in text or "429" in text:
            return "external_rate_limited"
        if "malformed" in text or "invalid" in text or "parse" in text:
            return "external_invalid_response"
        return "external_timeout"

    # ── Send ──────────────────────────────────────────────────────────────────

    async def send_operation(
        self, command: SendNotificationOperationCommand
    ) -> NotificationOperationRecord:
        """Validate, create deliveries, and enqueue the operation for processing.

        Processing order:
        1. Validate inputs.
        2. Reject operations in non-sendable states.
        3. Re-run validate_operation (always, even if already READY).
        4. Reject if validation cannot proceed (version mismatch, reconfirmation
           required, no sendable targets, external blocked, etc.).
        5. Create PENDING deliveries for SEND-disposition targets and SKIPPED
           deliveries for SKIP-disposition targets.
        6. Persist deliveries and set send_requested_at on the operation.
        7. Audit send_requested.
        8. Enqueue the operation. In inline mode the queue handler immediately
           calls process_operation. If enqueue fails, durable intent remains
           accepted and the operation is left READY (not SENDING).
        """
        _required(command.service_id, "service_id")
        _required(command.staff_id, "staff_id")
        _required(command.request_id, "request_id")

        # 1. Load operation
        operation = await self._repository.get_operation(
            command.service_id, command.operation_id
        )

        # 2. Reject non-sendable statuses upfront
        if operation.status in _REJECT_SEND_STATUSES:
            now = self._now()
            await self._audit(
                operation,
                "send_rejected",
                command.staff_id,
                {
                    "reason": operation.status.value,
                    "request_id": command.request_id,
                },
                now,
            )
            raise OperationNotSendableError(
                f"operation cannot be sent in status '{operation.status.value}'"
            )

        # A READY operation with a send reservation represents durable intent
        # whose temporary queue enqueue may have failed. Return that accepted
        # state without generating or enqueueing another command.
        if operation.send_requested_at is not None or await self._repository.get_deliveries(
            command.service_id, command.operation_id
        ):
            return operation

        # 3. Always re-validate before sending
        validate_cmd = ValidateNotificationOperationCommand(
            service_id=command.service_id,
            operation_id=command.operation_id,
            staff_id=command.staff_id,
            request_id=command.request_id,
        )
        summary = await self.validate_operation(validate_cmd)

        # Re-read after validation — status may now be BLOCKED_EXTERNAL_SYSTEM
        operation = await self._repository.get_operation(
            command.service_id, command.operation_id
        )

        # 4. Reject if validation did not clear the operation for sending
        if (operation.status is not OperationStatus.READY
                or operation.validated_at != summary.validated_at
                or operation.validation_snapshot != freeze_mapping(_validation_snapshot(summary))):
            raise OperationNotSendableError("operation changed after validation")
        if not summary.can_proceed or summary.requires_staff_reconfirmation:
            now = self._now()
            reason = (
                "requires_reconfirmation"
                if summary.requires_staff_reconfirmation
                else (summary.blocking_reason or "cannot_proceed")
            )
            await self._audit(
                operation,
                "send_rejected",
                command.staff_id,
                {
                    "reason": reason,
                    "request_id": command.request_id,
                },
                now,
            )
            raise OperationNotSendableError(f"operation cannot proceed: {reason}")

        if self._pre_send_guard is not None:
            try:
                self._pre_send_guard(
                    await self.get_operation(
                        command.service_id, command.operation_id
                    ),
                    summary,
                )
            except OperationNotSendableError:
                await self._audit(
                    operation,
                    "send_rejected",
                    command.staff_id,
                    {
                        "reason": "staging_line_send_guard",
                        "request_id": command.request_id,
                    },
                    self._now(),
                )
                raise

        # 5. Build delivery records from validation summary
        now = self._now()
        deliveries: list[NotificationDeliveryRecord] = []
        targets_by_member = {
            target.member_id: target
            for target in await self._repository.get_targets(
                command.service_id, command.operation_id
            )
        }
        for item in summary.target_results:
            target = targets_by_member[item.member_id]
            if item.delivery_disposition is ValidationDisposition.SEND:
                deliveries.append(
                    NotificationDeliveryRecord(
                        delivery_id=self._uuid(),
                        operation_id=command.operation_id,
                        member_id=item.member_id,
                        status=DeliveryStatus.PENDING,
                        request_id=command.request_id,
                        line_request_id=None,
                        error_code=None,
                        error_message=None,
                        created_at=now,
                        updated_at=now,
                        line_subject=(
                            target.line_subject if self._persist_line_subjects else None
                        ),
                    )
                )
            elif item.delivery_disposition is ValidationDisposition.SKIP:
                # 8. LINE not linked / ineligible → SKIPPED with reason stored as error_code
                deliveries.append(
                    NotificationDeliveryRecord(
                        delivery_id=self._uuid(),
                        operation_id=command.operation_id,
                        member_id=item.member_id,
                        status=DeliveryStatus.SKIPPED,
                        request_id=command.request_id,
                        line_request_id=None,
                        error_code=item.reason,
                        error_message=None,
                        created_at=now,
                        updated_at=now,
                        line_subject=(
                            target.line_subject if self._persist_line_subjects else None
                        ),
                    )
                )

        sendable_count = sum(
            1 for d in deliveries if d.status is DeliveryStatus.PENDING
        )
        skipped_count = sum(1 for d in deliveries if d.status is DeliveryStatus.SKIPPED)
        if not operation.job_version:
            raise OperationNotSendableError(
                "operation job version is required for notification command"
            )

        if self._organization_id_resolver is None:
            raise OperationNotSendableError(
                "organization identifier cannot be resolved"
            )
        organization_id = self._organization_id_resolver(command.service_id)
        if not isinstance(organization_id, str) or not organization_id.strip():
            raise OperationNotSendableError(
                "organization identifier cannot be resolved"
            )
        organization_id = organization_id.strip()

        outbox_records = tuple(
            NotificationOutboxRecord(
                outbox_id=uuid5(
                    uuid5(command.operation_id, f"command:{item.member_id}:{operation.message_version}"),
                    "admin-outbox",
                ),
                command_id=uuid5(
                    command.operation_id,
                    f"command:{item.member_id}:{operation.message_version}",
                ),
                operation_id=command.operation_id,
                target_id=uuid5(command.operation_id, f"target:{item.member_id}"),
                organization_id=organization_id,
                service_id=command.service_id,
                external_member_id=item.member_id,
                job_id=operation.job_id,
                job_version=operation.job_version,
                business_message=operation.message,
                message_version=operation.message_version,
                message_hash=operation.message_hash,
                idempotency_key=(
                    f"{command.operation_id}:{item.member_id}:"
                    f"{operation.message_version}"
                ),
                correlation_id=command.request_id,
                requested_at=now,
                created_at=now,
            )
            for item in summary.target_results
            if item.delivery_disposition is ValidationDisposition.SEND
        )

        if self._queue_gateway is None:
            raise InvalidNotificationCommandError(
                "queue gateway is required for send_operation"
            )

        # Reserve the send atomically. The persistent adapter repeats the
        # duplicate check while holding the operation row lock.
        if self._reservation_guard is not None:
            await self._reservation_guard(command.service_id, sendable_count)
        try:
            updated, _stored_deliveries = await self._repository.begin_send_attempt(
                command.service_id,
                command.operation_id,
                deliveries,
                outbox_records,
                self._audit_event(
                    operation,
                    "send_requested",
                    command.staff_id,
                    {
                        "request_id": command.request_id,
                        "sendable_count": sendable_count,
                        "skipped_count": skipped_count,
                    },
                    now,
                ),
                send_requested_at=now,
                expected_operation=operation,
            )
        except SendAttemptAlreadyExistsError as exc:
            await self._audit(
                operation,
                "send_rejected",
                command.staff_id,
                {
                    "reason": "send_already_requested",
                    "request_id": command.request_id,
                },
                self._now(),
            )
            raise OperationNotSendableError(
                "operation send was already requested"
            ) from exc

        # Queueing is a temporary execution mechanism. The committed Outbox is
        # the durable send intent and remains accepted if enqueueing fails.
        try:
            scoped_enqueue = getattr(
                self._queue_gateway,
                "enqueue_scoped_notification_operation",
                None,
            )
            if callable(scoped_enqueue):
                await scoped_enqueue(
                    service_id=command.service_id,
                    operation_id=command.operation_id,
                    request_id=command.request_id,
                )
            elif self._require_scoped_queue:
                raise QueueError("scoped queue capability is required")
            else:
                await self._queue_gateway.enqueue_notification_operation(
                    operation_id=command.operation_id,
                    request_id=command.request_id,
                )
        except QueueError:
            restored = await self._repository.get_operation(
                command.service_id, command.operation_id
            )
            try:
                await self._audit(
                    restored,
                    "enqueue_failed",
                    command.staff_id,
                    {
                        "reason": "queue_enqueue_failed",
                        "request_id": command.request_id,
                    },
                    self._now(),
                )
            except Exception as audit_error:
                # This audit is auxiliary and occurs after the send-intent
                # transaction committed. Its failure cannot undo acceptance.
                _logger.error(
                    "enqueue_failed audit append failed (%s)",
                    type(audit_error).__name__,
                )
            return restored

        # Return current state (COMPLETED/COMPLETED_WITH_ERRORS if inline processed)
        return await self._repository.get_operation(command.service_id, command.operation_id)

    # ── Process ───────────────────────────────────────────────────────────────

    async def process_operation(
        self, command: ProcessNotificationOperationCommand
    ) -> NotificationOperationRecord:
        """Process pending deliveries for an operation.

        Processing order:
        1. Load operation and current deliveries.
        2. Set operation status to SENDING.
        3. Filter to PENDING deliveries only (sent/failed/unknown/skipped are not
           re-processed — this makes the method idempotent on re-entry).
        4. For each PENDING delivery call LineMessageGateway.send_job_notification.
        5. On success: status → SENT, provider line_request_id and sent_at saved.
        6. On LineSendError: map to FAILED or UNKNOWN with sanitised error_code.
        7. On unexpected error: mark UNKNOWN.
        8. Continue processing remaining deliveries even after a single failure.
        9. After all pending deliveries are processed, aggregate counts and set
           operation status to COMPLETED or COMPLETED_WITH_ERRORS.
        10. Set completed_at and audit processing_completed.
        """
        # 1. Load operation and deliveries
        operation = await self._repository.get_operation(
            command.service_id, command.operation_id
        )
        deliveries = await self._repository.get_deliveries(
            command.service_id, command.operation_id
        )

        # A completed/replayed operation has no pending work.  Return before
        # changing status or emitting duplicate processing audit events.
        pending = [d for d in deliveries if d.status is DeliveryStatus.PENDING]
        if not pending:
            return operation

        if operation.status not in (OperationStatus.READY, OperationStatus.SENDING):
            raise OperationNotSendableError(
                f"operation cannot be processed in status '{operation.status.value}'"
            )

        # 2. Set SENDING
        sending = replace(operation, status=OperationStatus.SENDING)
        now = self._now()
        operation = await self._repository.update_operation_with_audit(
            command.service_id,
            command.operation_id,
            sending,
            self._audit_event(
                sending,
                "processing_started",
                None,
                {"pending_count": len(pending)},
                now,
            ),
        )

        if self._line_sender is None:
            raise InvalidNotificationCommandError(
                "line messaging gateway is required for process_operation"
            )

        # 5. Build JobNotificationMessage from operation fields.
        # The notification body is taken from operation.message.
        # Fixed items (center_name, job_detail_url) are derived from fields
        # available without additional external calls, keeping the Application
        # Service free of raw LINE payloads and external JSON.
        job_message = (
            self._message_factory(operation)
            if self._message_factory
            else JobNotificationMessage(
                message_body=(
                    f"{operation.message.greeting}\n\n"
                    f"{operation.message.introduction}\n\n"
                    f"{operation.message.note}"
                ),
                job_detail_url=f"https://demo.local/jobs/{operation.job_id}",
                center_name=operation.service_id,
                inquiry_text=None,
            )
        )

        sent_this_round = 0
        failed_this_round = 0
        unknown_this_round = 0

        # 4, 6-8, 13. Process each PENDING delivery; continue on individual failure
        for delivery in pending:
            try:
                line_subject = delivery.line_subject
                if line_subject is None and self._line_subject_resolver is not None:
                    line_subject = self._line_subject_resolver(
                        command.service_id, delivery.member_id
                    )
                if not line_subject:
                    raise InvalidNotificationCommandError(
                        "LINE destination is unavailable"
                    )
                result = await self._line_sender.send_job_notification(
                    service_id=command.service_id,
                    line_subject=line_subject,
                    message=job_message,
                    request_id=delivery.request_id or command.request_id,
                )
                # 7-9. Success: save provider request ID and sent_at
                updated_delivery = replace(
                    delivery,
                    status=DeliveryStatus.SENT,
                    line_request_id=result.line_request_id,
                    sent_at=result.accepted_at,
                )
                sent_this_round += 1
            except LineSendError as exc:
                # 10-11. Map known LINE exception to typed error code
                status, error_code, error_message = _map_line_exception(exc)
                updated_delivery = replace(
                    delivery,
                    status=status,
                    error_code=error_code,
                    error_message=error_message,
                )
                if status is DeliveryStatus.FAILED:
                    failed_this_round += 1
                else:
                    unknown_this_round += 1
            except Exception:
                # 11. Unexpected error → UNKNOWN; do NOT store raw exception text
                updated_delivery = replace(
                    delivery,
                    status=DeliveryStatus.UNKNOWN,
                    error_code="unexpected_error",
                    error_message="An unexpected error occurred during delivery",
                )
                unknown_this_round += 1

            await self._repository.update_delivery(
                command.service_id,
                command.operation_id,
                delivery.delivery_id,
                updated_delivery,
            )

        # 14. Re-read all deliveries to get authoritative counts for status roll-up
        now = self._now()
        all_deliveries = await self._repository.get_deliveries(
            command.service_id, command.operation_id
        )
        sent_count = sum(1 for d in all_deliveries if d.status is DeliveryStatus.SENT)
        failed_count = sum(
            1 for d in all_deliveries if d.status is DeliveryStatus.FAILED
        )
        unknown_count = sum(
            1 for d in all_deliveries if d.status is DeliveryStatus.UNKNOWN
        )
        skipped_count = sum(
            1 for d in all_deliveries if d.status is DeliveryStatus.SKIPPED
        )

        # Aggregate delivery_processed audit (one event, not per-delivery)
        await self._audit(
            operation,
            "delivery_processed",
            None,
            {
                "sent_count": sent_this_round,
                "failed_count": failed_this_round,
                "unknown_count": unknown_this_round,
                "processed_count": len(pending),
            },
            now,
        )

        # 15-16. Determine final operation status
        final_status = (
            OperationStatus.COMPLETED_WITH_ERRORS
            if failed_count > 0 or unknown_count > 0
            else OperationStatus.COMPLETED
        )

        # 17. Set completed_at
        completed_record = replace(
            operation, status=final_status, completed_at=now
        )
        completed = await self._repository.update_operation_with_audit(
            command.service_id,
            command.operation_id,
            completed_record,
            self._audit_event(
                completed_record,
                "processing_completed",
                None,
                {
                    "sent_count": sent_count,
                    "failed_count": failed_count,
                    "unknown_count": unknown_count,
                    "skipped_count": skipped_count,
                    "final_status": final_status.value,
                },
                now,
            ),
        )

        return completed

    # ── Query / admin ─────────────────────────────────────────────────────────

    async def list_deliveries(
        self, service_id: str, operation_id: UUID
    ) -> tuple[NotificationDeliveryRecord, ...]:
        return await self._repository.get_deliveries(service_id, operation_id)

    async def reset_demo_data(self) -> ResetDemoDataResult:
        await self._repository.reset()
        return ResetDemoDataResult(reset=True)

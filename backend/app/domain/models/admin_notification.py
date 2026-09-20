"""Admin-owned notification persistence records.

``line_subject`` and ``line_request_id`` remain temporary compatibility fields
for the current pre-split send flow. Persistent Admin adapters must not store
them; they are removed from Admin domain use in a later roadmap phase.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping, TypeAlias
from uuid import UUID

from app.domain.enums.enums import (
    DeliveryStatus,
    NotificationEligibilityReason,
    OperationStatus,
)
from app.domain.enums.notification_type import NotificationType

AuditScalar: TypeAlias = str | int | float | bool | None
AuditValue: TypeAlias = AuditScalar | tuple["AuditValue", ...] | Mapping[str, "AuditValue"]
ValidationSnapshot: TypeAlias = Mapping[str, AuditValue]


def _freeze_json_value(value: object) -> AuditValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json_value(item) for item in value)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("mapping keys must be strings")
        return MappingProxyType(
            {key: _freeze_json_value(item) for key, item in value.items()}
        )
    raise ValueError("value must contain only JSON-compatible values")


def freeze_mapping(value: Mapping[str, object]) -> Mapping[str, AuditValue]:
    frozen = _freeze_json_value(value)
    if not isinstance(frozen, Mapping):
        raise ValueError("value must be a mapping")
    return frozen


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    greeting: str
    introduction: str
    note: str


@dataclass(frozen=True, slots=True)
class NotificationOperationRecord:
    operation_id: UUID
    service_id: str
    job_id: str
    job_version: str | None
    notification_type: NotificationType
    message: NotificationMessage
    status: OperationStatus
    created_by_staff_id: str
    created_at: datetime
    updated_at: datetime
    validated_at: datetime | None = None
    send_requested_at: datetime | None = None
    completed_at: datetime | None = None
    message_version: int = 1
    message_hash: str = ""
    validation_snapshot: ValidationSnapshot | None = None

    def __post_init__(self) -> None:
        if self.message_version < 1:
            raise ValueError("message_version must be positive")
        if self.validation_snapshot is not None:
            object.__setattr__(
                self, "validation_snapshot", freeze_mapping(self.validation_snapshot)
            )


@dataclass(frozen=True, slots=True)
class NotificationTargetRecord:
    operation_id: UUID
    member_id: str
    selected: bool
    line_linked: bool
    eligibility: NotificationEligibilityReason | None
    reason: str | None
    created_at: datetime
    updated_at: datetime
    line_subject: str | None = None


@dataclass(frozen=True, slots=True)
class NotificationDeliveryRecord:
    delivery_id: UUID
    operation_id: UUID
    member_id: str
    status: DeliveryStatus
    request_id: str | None
    line_request_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None = None
    line_subject: str | None = None


@dataclass(frozen=True, slots=True)
class NotificationAuditEvent:
    audit_id: UUID
    operation_id: UUID
    event_type: str
    staff_id: str | None
    details: Mapping[str, AuditValue]
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", freeze_mapping(self.details))


class NotificationOutboxState(str, Enum):
    PENDING = "pending"
    DELIVERING = "delivering"
    ACCEPTED = "accepted"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"
    RECONCILED = "reconciled"


@dataclass(frozen=True, slots=True)
class NotificationOutboxRecord:
    """Admin-owned durable intent for one business member command."""

    outbox_id: UUID
    command_id: UUID
    operation_id: UUID
    target_id: UUID
    organization_id: str
    service_id: str
    external_member_id: str
    job_id: str
    job_version: str
    business_message: NotificationMessage
    message_version: int
    message_hash: str
    idempotency_key: str
    correlation_id: str
    requested_at: datetime
    created_at: datetime
    state: NotificationOutboxState = NotificationOutboxState.PENDING
    lease_expires_at: datetime | None = None
    claim_token: UUID | None = None

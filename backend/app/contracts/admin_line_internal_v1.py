"""Generated Admin consumer models for line-internal-api-v1.openapi.json.

This module is distributable with the contract artifact and deliberately has
no import from the LINE provider's private schema implementation.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

CONTRACT_ARTIFACT = "line-internal-api-v1.openapi.json"
CONTRACT_VERSION = "1.0.0"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServiceOrganizationScope(ContractModel):
    organization_id: str = Field(min_length=1, max_length=128)
    service_id: str = Field(min_length=1, max_length=128)


class BusinessNotificationMessage(ContractModel):
    greeting: str = Field(min_length=1)
    introduction: str = Field(min_length=1)
    note: str = Field(min_length=1)


class NotificationCommand(ContractModel):
    command_id: UUID
    operation_id: UUID
    target_id: UUID
    scope: ServiceOrganizationScope
    external_member_id: str = Field(min_length=1, max_length=128)
    job_id: str = Field(min_length=1, max_length=128)
    job_version: str = Field(min_length=1, max_length=128)
    business_message: BusinessNotificationMessage
    message_version: str = Field(min_length=1, max_length=128)
    message_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=255)
    correlation_id: str = Field(min_length=1, max_length=255)
    requested_at: datetime


class NotificationCommandStatus(str, Enum):
    ACCEPTED = "accepted"
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    UNKNOWN = "unknown"
    REJECTED = "rejected"
    RECIPIENT_NOT_LINKED = "recipient_not_linked"


class NotificationResult(ContractModel):
    command_id: UUID
    delivery_id: UUID | None = None
    operation_id: UUID
    target_id: UUID
    external_member_id: str = Field(min_length=1, max_length=128)
    status: NotificationCommandStatus
    reason_code: str | None = Field(default=None, max_length=128)
    accepted_at: datetime | None = None
    updated_at: datetime


class LinkageStatusBatchRequest(ContractModel):
    scope: ServiceOrganizationScope
    external_member_ids: tuple[str, ...] = Field(min_length=1, max_length=500)


class LinkageStatusItem(ContractModel):
    external_member_id: str = Field(min_length=1, max_length=128)
    line_linked: bool


class LinkageStatusBatchResponse(ContractModel):
    items: tuple[LinkageStatusItem, ...]


class LiffDeepLinkRequest(ContractModel):
    scope: ServiceOrganizationScope
    job_id: str = Field(min_length=1, max_length=128)


class LiffDeepLinkResponse(ContractModel):
    canonical_deep_link: HttpUrl


class StagingSendReadinessRequest(ContractModel):
    scope: ServiceOrganizationScope


class StagingSendReadinessResponse(ContractModel):
    ready: bool
    live_send_enabled: bool
    max_recipients: int
    message_prefix: str | None = None
    blocking_reasons: tuple[str, ...] = ()

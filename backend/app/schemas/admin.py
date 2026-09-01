from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums.enums import DeliveryStatus, JobStatus, OperationStatus
from app.domain.enums.notification_type import NotificationType


class AdminJobSummaryResponse(BaseModel):
    job_id: str
    title: str
    location: str | None
    status: JobStatus
    openings: int = 1
    version: str
    summary: str | None
    work_days: str | None = None
    work_time: str | None = None


class AdminJobDetailResponse(BaseModel):
    job_id: str
    title: str
    description: str
    location: str | None
    conditions: tuple[str, ...]
    status: JobStatus
    openings: int = 1
    version: str
    job_url: str
    contact: str | None


class AdminCandidateResponse(BaseModel):
    member_id: str
    display_name: str
    line_linked: bool
    eligible: bool
    reason: str | None
    selected: bool
    preference_summary: str | None = None


class AdminOperationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1)
    notification_type: NotificationType
    greeting: str = Field(min_length=1)
    introduction: str = Field(min_length=1)
    note: str = Field(min_length=1)


class AdminOperationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    greeting: str = Field(min_length=1)
    introduction: str = Field(min_length=1)
    note: str = Field(min_length=1)


class AdminTargetsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_member_ids: tuple[str, ...]


class AdminMessageResponse(BaseModel):
    greeting: str
    introduction: str
    note: str


class AdminOperationResponse(BaseModel):
    operation_id: UUID
    job_id: str
    job_version: str | None
    notification_type: NotificationType
    message: AdminMessageResponse
    status: OperationStatus
    target_count: int
    selected_count: int
    validated_at: datetime | None
    send_requested_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminValidationResponse(BaseModel):
    operation_id: UUID
    status: OperationStatus
    can_proceed: bool
    selected_count: int
    sendable_count: int
    skipped_count: int
    reasons: tuple[str, ...]
    version_changed: bool
    external_system_blocked: bool


class AdminDeliveryResponse(BaseModel):
    delivery_id: UUID
    member_id: str
    status: DeliveryStatus
    reason_code: str | None
    created_at: datetime
    sent_at: datetime | None
    updated_at: datetime


class AdminDeliverySummary(BaseModel):
    pending: int
    sent: int
    failed: int
    unknown: int
    skipped: int


class AdminDeliveriesResponse(BaseModel):
    items: tuple[AdminDeliveryResponse, ...]
    summary: AdminDeliverySummary


class AdminResetResponse(BaseModel):
    reset: bool


class AdminLineSendModeResponse(BaseModel):
    mode: str
    max_recipients: int | None
    message_prefix: str | None
    live_send_enabled: bool | None = None
    ready: bool | None = None
    blocking_reasons: tuple[str, ...] = ()


class AdminNotificationLinkResponse(BaseModel):
    url: str

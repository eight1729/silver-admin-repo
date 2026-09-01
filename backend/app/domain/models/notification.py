from dataclasses import dataclass
from datetime import datetime

from app.domain.enums.enums import NotificationEligibilityReason


@dataclass(frozen=True, slots=True)
class MemberValidationResult:
    external_member_id: str
    eligible: bool
    reason_code: NotificationEligibilityReason | None

    def __post_init__(self) -> None:
        if self.eligible and self.reason_code is not None:
            raise ValueError(
                "reason_code must be None when eligible is True"
            )


@dataclass(frozen=True, slots=True)
class NotificationValidationResult:
    external_job_id: str
    job_eligible: bool
    current_job_version: str
    job_reason_code: NotificationEligibilityReason | None
    members: tuple[MemberValidationResult, ...]
    validated_at: datetime
    external_request_id: str | None

    def __post_init__(self) -> None:
        if self.job_eligible and self.job_reason_code is not None:
            raise ValueError(
                "job_reason_code must be None when job_eligible is True"
            )


@dataclass(frozen=True, slots=True)
class QueueEnqueueResult:
    task_name: str
    enqueued_at: datetime

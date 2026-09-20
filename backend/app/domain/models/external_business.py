from dataclasses import dataclass
from datetime import datetime

from app.domain.enums.enums import JobStatus, LinkEligibilityReason, MemberVerificationStatus


@dataclass(frozen=True, slots=True)
class MemberVerificationInput:
    member_number: str
    name: str


@dataclass(frozen=True, slots=True)
class MemberVerificationResult:
    status: MemberVerificationStatus
    external_member_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, MemberVerificationStatus):
            raise ValueError("status must be a MemberVerificationStatus")
        if self.status is MemberVerificationStatus.UNIQUE_MATCH:
            if not isinstance(self.external_member_id, str) or not self.external_member_id:
                raise ValueError("unique match requires an external_member_id")
        elif self.external_member_id is not None:
            raise ValueError("only unique match may contain an external_member_id")


@dataclass(frozen=True, slots=True)
class ExternalMemberSummary:
    external_member_id: str
    display_label: str | None


@dataclass(frozen=True, slots=True)
class LinkEligibility:
    external_member_id: str
    eligible: bool
    reason_code: LinkEligibilityReason | None
    checked_at: datetime

    def __post_init__(self) -> None:
        if self.eligible and self.reason_code is not None:
            raise ValueError(
                "reason_code must be None when eligible is True"
            )


@dataclass(frozen=True, slots=True)
class ExternalJobSummary:
    external_job_id: str
    title: str
    summary: str | None
    work_location_summary: str | None
    work_schedule_summary: str | None
    application_deadline: datetime | None
    status: JobStatus
    version: str
    updated_at: datetime | None
    work_days: str | None = None
    work_time: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalJobDetail:
    external_job_id: str
    title: str
    description: str
    work_location: str | None
    work_schedule_text: str | None
    application_deadline: datetime | None
    required_conditions: tuple[str, ...]
    status: JobStatus
    version: str
    updated_at: datetime | None
    staff_notes: str | None
    job_url: str | None = None


@dataclass(frozen=True, slots=True)
class JobSearchQuery:
    keyword: str | None = None
    statuses: tuple[JobStatus, ...] | None = None
    updated_from: datetime | None = None
    updated_to: datetime | None = None
    page: int = 1
    page_size: int = 20

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError(f"page must be >= 1, got {self.page}")
        if self.page_size < 1:
            raise ValueError(f"page_size must be >= 1, got {self.page_size}")


@dataclass(frozen=True, slots=True)
class PagedExternalJobs:
    items: tuple[ExternalJobSummary, ...]
    page: int
    page_size: int
    total_count: int | None
    has_next: bool


@dataclass(frozen=True, slots=True)
class CandidateMember:
    external_member_id: str
    display_label: str | None
    eligible: bool
    reason_codes: tuple[str, ...]
    match_rank: int | None
    line_subject: str | None = None
    preference_summary: str | None = None

    def __post_init__(self) -> None:
        if self.eligible and self.reason_codes:
            raise ValueError(
                "reason_codes must be empty when eligible is True"
            )

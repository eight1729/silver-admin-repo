"""Admin-owned wire contract; business projections remain domain-owned."""

from typing import Annotated, Literal
from dataclasses import dataclass
from datetime import datetime
from app.domain.enums.enums import JobStatus

from pydantic import BaseModel, ConfigDict, Field

ADMIN_INTERNAL_CONTRACT_VERSION = "1.0.0"


class InternalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    service_id: str = Field(min_length=1, max_length=128)


class MemberVerificationRequest(InternalRequest):
    member_number: str = Field(min_length=1)
    name: str = Field(min_length=1)


class MemberRequest(InternalRequest):
    external_member_id: str = Field(min_length=1)


class JobDetailRequest(InternalRequest):
    external_job_id: str = Field(min_length=1)


class NoMemberMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["no_match"] = "no_match"


class UniqueMemberMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["unique_match"] = "unique_match"
    external_member_id: str = Field(min_length=1)


class MultipleMemberMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["multiple_match"] = "multiple_match"


MemberVerificationResponse = Annotated[
    NoMemberMatch | UniqueMemberMatch | MultipleMemberMatch,
    Field(discriminator="status"),
]


class InternalErrorDetail(BaseModel):
    error: Literal[
        "authentication_failed", "authentication_unavailable", "scope_forbidden",
        "invalid_request", "resource_not_found", "external_system_unavailable",
        "internal_error",
    ]


class InternalErrorResponse(BaseModel):
    detail: InternalErrorDetail


# Explicit v1 allowlist: Admin-only display attributes must never widen the S2S wire contract.


@dataclass(frozen=True, slots=True)
class ExternalMemberSummary:
    external_member_id: str
    display_label: str | None


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

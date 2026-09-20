"""Admin-owned wire contract; business projections remain domain-owned."""

from typing import Annotated, Literal

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

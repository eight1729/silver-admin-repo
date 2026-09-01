"""Fake implementation of ExternalBusinessGateway for use in tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.models.external_business import (
    CandidateMember,
    ExternalJobDetail,
    ExternalJobSummary,
    JobSearchQuery,
    LinkEligibility,
    PagedExternalJobs,
)
from app.domain.models.notification import NotificationValidationResult
from app.domain.errors.errors import ExternalBusinessNotConfiguredError


class NotConfiguredError(ExternalBusinessNotConfiguredError):
    """Raised when a Fake method is called but no return value has been configured."""


@dataclass
class _Call:
    method: str
    kwargs: dict[str, Any]


class FakeExternalBusinessGateway:
    """Test double for ExternalBusinessGateway.

    Usage::

        fake = FakeExternalBusinessGateway()

        # Configure a fixed return value
        fake.link_eligibility_result = LinkEligibility(...)

        # Or raise on the next call
        fake.raise_on_next_check_link_eligibility = ExternalMemberNotFoundError("not found")

        # Inspect calls
        assert fake.calls[0].method == "check_link_eligibility"
        assert fake.calls[0].kwargs["external_member_id"] == "M001"
    """

    def __init__(self) -> None:
        self.calls: list[_Call] = []

        # Configurable return values (None = not configured → NotConfiguredError)
        self.link_eligibility_result: LinkEligibility | None = None
        self.recommended_jobs_result: list[ExternalJobSummary] | None = None
        self.job_detail_result: ExternalJobDetail | None = None
        self.job_detail_results: dict[str, ExternalJobDetail] = {}
        self.search_jobs_result: PagedExternalJobs | None = None
        self.candidate_members_result: list[CandidateMember] | None = None
        self.validation_result: NotificationValidationResult | None = None
        self.validation_results: dict[str, NotificationValidationResult] = {}
        # Demo scenario control may configure one safe, typed failure for every
        # gateway call until the scenario is reset. Tests can continue using
        # the existing one-shot attributes below.
        self.persistent_error: BaseException | None = None

        # Raise-on-next: set to an exception instance to raise it once, then clear
        self.raise_on_next_check_link_eligibility: BaseException | None = None
        self.raise_on_next_list_recommended_jobs: BaseException | None = None
        self.raise_on_next_get_job_detail: BaseException | None = None
        self.raise_on_next_search_jobs: BaseException | None = None
        self.raise_on_next_list_candidate_members: BaseException | None = None
        self.raise_on_next_validate_notification_targets: BaseException | None = None

    def _record(self, method: str, kwargs: dict[str, Any]) -> None:
        self.calls.append(_Call(method=method, kwargs=kwargs))

    def _maybe_raise(self, attr: str) -> None:
        exc = getattr(self, attr)
        if exc is not None:
            setattr(self, attr, None)
            raise exc
        if self.persistent_error is not None:
            raise self.persistent_error

    async def check_link_eligibility(
        self,
        *,
        external_organization_id: str,
        external_member_id: str,
    ) -> LinkEligibility:
        self._record(
            "check_link_eligibility",
            {
                "external_organization_id": external_organization_id,
                "external_member_id": external_member_id,
            },
        )
        self._maybe_raise("raise_on_next_check_link_eligibility")
        if self.link_eligibility_result is None:
            raise NotConfiguredError(
                "FakeExternalBusinessGateway.link_eligibility_result is not set"
            )
        return self.link_eligibility_result

    async def list_recommended_jobs(
        self,
        *,
        external_organization_id: str,
        external_member_id: str,
    ) -> list[ExternalJobSummary]:
        self._record(
            "list_recommended_jobs",
            {
                "external_organization_id": external_organization_id,
                "external_member_id": external_member_id,
            },
        )
        self._maybe_raise("raise_on_next_list_recommended_jobs")
        if self.recommended_jobs_result is None:
            raise NotConfiguredError(
                "FakeExternalBusinessGateway.recommended_jobs_result is not set"
            )
        return self.recommended_jobs_result

    async def get_job_detail(
        self,
        *,
        external_organization_id: str,
        external_job_id: str,
    ) -> ExternalJobDetail:
        self._record(
            "get_job_detail",
            {
                "external_organization_id": external_organization_id,
                "external_job_id": external_job_id,
            },
        )
        self._maybe_raise("raise_on_next_get_job_detail")
        if (
            self.job_detail_result is not None
            and self.job_detail_result.external_job_id == external_job_id
        ):
            return self.job_detail_result
        result = self.job_detail_results.get(external_job_id)
        if result is not None:
            return result
        if self.job_detail_result is None:
            raise NotConfiguredError(
                "FakeExternalBusinessGateway.job_detail_result is not set"
            )
        return self.job_detail_result

    async def search_jobs(
        self,
        *,
        external_organization_id: str,
        query: JobSearchQuery,
    ) -> PagedExternalJobs:
        self._record(
            "search_jobs",
            {
                "external_organization_id": external_organization_id,
                "query": query,
            },
        )
        self._maybe_raise("raise_on_next_search_jobs")
        if self.search_jobs_result is None:
            raise NotConfiguredError(
                "FakeExternalBusinessGateway.search_jobs_result is not set"
            )
        return self.search_jobs_result

    async def list_candidate_members(
        self,
        *,
        external_organization_id: str,
        external_job_id: str,
    ) -> list[CandidateMember]:
        self._record(
            "list_candidate_members",
            {
                "external_organization_id": external_organization_id,
                "external_job_id": external_job_id,
            },
        )
        self._maybe_raise("raise_on_next_list_candidate_members")
        if self.candidate_members_result is None:
            raise NotConfiguredError(
                "FakeExternalBusinessGateway.candidate_members_result is not set"
            )
        return self.candidate_members_result

    async def validate_notification_targets(
        self,
        *,
        external_organization_id: str,
        external_job_id: str,
        expected_job_version: str,
        external_member_ids: list[str],
    ) -> NotificationValidationResult:
        self._record(
            "validate_notification_targets",
            {
                "external_organization_id": external_organization_id,
                "external_job_id": external_job_id,
                "expected_job_version": expected_job_version,
                "external_member_ids": external_member_ids,
            },
        )
        self._maybe_raise("raise_on_next_validate_notification_targets")
        if (
            self.validation_result is not None
            and self.validation_result.external_job_id == external_job_id
        ):
            return self.validation_result
        result = self.validation_results.get(external_job_id)
        if result is not None:
            return result
        if self.validation_result is None:
            raise NotConfiguredError(
                "FakeExternalBusinessGateway.validation_result is not set"
            )
        return self.validation_result

    def reset(self) -> None:
        """Clear call history and all raise_on_next_* flags. Result values are kept."""
        self.calls.clear()
        self.raise_on_next_check_link_eligibility = None
        self.raise_on_next_list_recommended_jobs = None
        self.raise_on_next_get_job_detail = None
        self.raise_on_next_search_jobs = None
        self.raise_on_next_list_candidate_members = None
        self.raise_on_next_validate_notification_targets = None
        self.persistent_error = None

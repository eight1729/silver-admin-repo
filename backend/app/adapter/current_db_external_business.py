"""Read-only mapping for the human-confirmed pre-release Current DB schema.

These table clauses describe reads only: no shared metadata, reflection or DDL.
They are not the schema contract of a future production business provider.
"""

from collections.abc import Mapping
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Text, Uuid, and_, column, func, or_, select, table
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domain.enums.enums import JobStatus, MemberVerificationStatus
from app.domain.errors.errors import (
    ExternalBusinessNotConfiguredError, ExternalJobNotFoundError,
    ExternalMemberNotFoundError, ExternalSystemUnavailableError,
)
from app.domain.models.external_business import (
    CandidateMember, ExternalJobDetail, ExternalJobSummary, ExternalMemberSummary,
    JobSearchQuery, LinkEligibility, MemberVerificationInput, MemberVerificationResult,
    PagedExternalJobs,
)
from app.domain.models.notification import MemberValidationResult, NotificationValidationResult
from app.domain.enums.enums import NotificationEligibilityReason
from app.domain.ports.organization_service_scope import OrganizationServiceScopeNotConfiguredError


_members = table(
    "members", column("id", Uuid), column("member_code", Text),
    column("full_name", Text), column("center_code", Text), schema="public",
)
_jobs = table(
    "jobs", column("id", Uuid), column("job_code", Text), column("title", Text), column("summary", Text),
    column("location_text", Text), column("work_date_text", Text),
    column("status", Text), column("updated_at", DateTime(timezone=True)),
    column("center_code", Text), schema="public",
)
_recommendations = table(
    "job_recommendation_flags", column("member_id", Uuid), column("job_id", Uuid),
    column("center_code", Text), column("is_recommended", Boolean), schema="public",
)


class CurrentDbExternalBusinessGateway:
    def __init__(self, engine: AsyncEngine, centers_by_organization: Mapping[str, str]) -> None:
        if not centers_by_organization or any(
            not isinstance(value, str) or not value or value != value.strip()
            for pair in centers_by_organization.items() for value in pair
        ):
            raise ExternalBusinessNotConfiguredError("Current DB business scopes are not configured")
        self._engine = engine
        self._centers = dict(centers_by_organization)

    def _center(self, organization_id: str) -> str:
        try:
            return self._centers[organization_id]
        except KeyError:
            raise OrganizationServiceScopeNotConfiguredError("business scope is not configured") from None

    async def _rows(self, statement):
        try:
            async with self._engine.connect() as connection:
                return (await connection.execute(statement)).mappings().all()
        except (SQLAlchemyError, TimeoutError, OSError):
            # SQL exceptions may contain bound PII and connection information.
            raise ExternalSystemUnavailableError("Current DB business data is unavailable") from None

    @staticmethod
    def _member_id(value: str) -> UUID:
        try:
            return UUID(value)
        except (ValueError, TypeError, AttributeError):
            raise ExternalMemberNotFoundError("member was not found") from None

    @staticmethod
    def _job_id(value: str) -> UUID:
        try:
            return UUID(value)
        except (ValueError, TypeError, AttributeError):
            raise ExternalJobNotFoundError("job was not found") from None

    @staticmethod
    def _revision(row) -> tuple[datetime, str]:
        updated = row["updated_at"]
        if not isinstance(updated, datetime) or updated.utcoffset() is None:
            raise ExternalSystemUnavailableError("Current DB job revision is unavailable")
        updated = updated.astimezone(timezone.utc)
        return updated, updated.isoformat()

    @staticmethod
    def _status(row) -> JobStatus:
        try:
            return JobStatus(row["status"])
        except ValueError:
            return JobStatus.UNKNOWN

    @classmethod
    def _job_summary(cls, row) -> ExternalJobSummary:
        updated, version = cls._revision(row)
        return ExternalJobSummary(
            external_job_id=str(row["id"]), title=row["title"], summary=row["summary"],
            work_location_summary=row["location_text"], work_schedule_summary=row["work_date_text"],
            application_deadline=None, status=cls._status(row), version=version, updated_at=updated,
        )

    async def verify_member(
        self, *, external_organization_id: str, verification: MemberVerificationInput,
    ) -> MemberVerificationResult:
        center = self._center(external_organization_id)
        rows = await self._rows(select(_members.c.id).where(
            _members.c.center_code == center,
            _members.c.member_code == verification.member_number,
            _members.c.full_name == verification.name,
        ).limit(2))
        if not rows:
            return MemberVerificationResult(MemberVerificationStatus.NO_MATCH)
        if len(rows) > 1:
            return MemberVerificationResult(MemberVerificationStatus.MULTIPLE_MATCH)
        return MemberVerificationResult(MemberVerificationStatus.UNIQUE_MATCH, str(rows[0]["id"]))

    async def get_member_summary(
        self, *, external_organization_id: str, external_member_id: str,
    ) -> ExternalMemberSummary:
        center = self._center(external_organization_id)
        rows = await self._rows(select(_members.c.id, _members.c.full_name).where(
            _members.c.center_code == center, _members.c.id == self._member_id(external_member_id),
        ))
        if not rows:
            raise ExternalMemberNotFoundError("member was not found")
        return ExternalMemberSummary(str(rows[0]["id"]), rows[0]["full_name"])

    async def list_recommended_jobs(
        self, *, external_organization_id: str, external_member_id: str,
    ) -> list[ExternalJobSummary]:
        center = self._center(external_organization_id)
        member_id = self._member_id(external_member_id)
        # Distinguish an absent/out-of-scope member from no recommendations.
        await self.get_member_summary(
            external_organization_id=external_organization_id, external_member_id=external_member_id,
        )
        rows = await self._rows(select(_jobs).select_from(
            _members.join(_recommendations, _recommendations.c.member_id == _members.c.id)
            .join(_jobs, _jobs.c.id == _recommendations.c.job_id)
        ).where(
            _members.c.id == member_id, _members.c.center_code == center,
            _recommendations.c.center_code == center, _recommendations.c.is_recommended.is_(True),
            _jobs.c.center_code == center,
        ).order_by(_jobs.c.id))
        return [self._job_summary(row) for row in rows]

    async def get_job_detail(
        self, *, external_organization_id: str, external_job_id: str,
    ) -> ExternalJobDetail:
        center = self._center(external_organization_id)
        rows = await self._rows(select(_jobs).where(
            _jobs.c.center_code == center, _jobs.c.id == self._job_id(external_job_id),
        ))
        if not rows:
            raise ExternalJobNotFoundError("job was not found")
        row = rows[0]
        updated, version = self._revision(row)
        return ExternalJobDetail(
            external_job_id=str(row["id"]), title=row["title"], description=row["summary"] or "",
            work_location=row["location_text"], work_schedule_text=row["work_date_text"],
            application_deadline=None, required_conditions=(), status=self._status(row),
            version=version, updated_at=updated, staff_notes=None,
        )

    # These capabilities have no confirmed mapping in this four-use-case slice.
    # Keep the complete port shape while failing explicitly, without Fake data.
    async def check_link_eligibility(
        self, *, external_organization_id: str, external_member_id: str,
    ) -> LinkEligibility:
        raise ExternalBusinessNotConfiguredError("link eligibility is not configured")

    async def search_jobs(
        self, *, external_organization_id: str, query: JobSearchQuery,
    ) -> PagedExternalJobs:
        center = self._center(external_organization_id)
        conditions = [_jobs.c.center_code == center]
        if query.statuses:
            conditions.append(_jobs.c.status.in_([status.value for status in query.statuses]))
        if query.updated_from is not None:
            conditions.append(_jobs.c.updated_at >= query.updated_from)
        if query.updated_to is not None:
            conditions.append(_jobs.c.updated_at <= query.updated_to)
        if query.keyword and query.keyword.strip():
            pattern = f"%{query.keyword.strip()}%"
            conditions.append(or_(_jobs.c.title.ilike(pattern), _jobs.c.summary.ilike(pattern),
                                  _jobs.c.location_text.ilike(pattern)))
        where = and_(*conditions)
        count_rows = await self._rows(select(func.count()).select_from(_jobs).where(where))
        total = int(count_rows[0][0]) if count_rows else 0
        rows = await self._rows(select(_jobs).where(where).order_by(_jobs.c.updated_at.desc(), _jobs.c.id)
                                .offset((query.page - 1) * query.page_size).limit(query.page_size))
        return PagedExternalJobs(tuple(self._job_summary(row) for row in rows), query.page, query.page_size,
                                 total, (query.page * query.page_size) < total)

    async def list_candidate_members(
        self, *, external_organization_id: str, external_job_id: str,
    ) -> list[CandidateMember]:
        center = self._center(external_organization_id)
        job_id = self._job_id(external_job_id)
        rows = await self._rows(select(_members.c.id, _members.c.full_name).select_from(
            _members.join(_recommendations, _recommendations.c.member_id == _members.c.id)
            .join(_jobs, _jobs.c.id == _recommendations.c.job_id)
        ).where(_jobs.c.id == job_id, _jobs.c.center_code == center,
                _members.c.center_code == center, _recommendations.c.center_code == center,
                _recommendations.c.is_recommended.is_(True)).order_by(_members.c.id))
        return [CandidateMember(str(row["id"]), row["full_name"], True, (), None) for row in rows]

    async def validate_notification_targets(
        self, *, external_organization_id: str, external_job_id: str,
        expected_job_version: str, external_member_ids: list[str],
    ) -> NotificationValidationResult:
        center = self._center(external_organization_id)
        job_id = self._job_id(external_job_id)
        jobs = await self._rows(select(_jobs).where(_jobs.c.id == job_id, _jobs.c.center_code == center))
        now = datetime.now(timezone.utc)
        if not jobs:
            return NotificationValidationResult(external_job_id, False, "", NotificationEligibilityReason.JOB_NOT_FOUND, (), now, None)
        job = jobs[0]
        _, current_version = self._revision(job)
        job_reason = None if self._status(job) is JobStatus.PUBLISHED else {
            JobStatus.CLOSED: NotificationEligibilityReason.JOB_CLOSED,
            JobStatus.PAUSED: NotificationEligibilityReason.JOB_PAUSED,
            JobStatus.CANCELLED: NotificationEligibilityReason.JOB_CANCELLED,
        }.get(self._status(job), NotificationEligibilityReason.UNKNOWN)
        member_ids = []
        for raw_id in external_member_ids:
            try:
                member_ids.append(self._member_id(raw_id))
            except ExternalMemberNotFoundError:
                continue
        rows = await self._rows(select(_members.c.id, _recommendations.c.is_recommended).select_from(
            _members.outerjoin(_recommendations, and_(_recommendations.c.member_id == _members.c.id,
                _recommendations.c.job_id == job_id, _recommendations.c.center_code == center))
        ).where(_members.c.id.in_(member_ids), _members.c.center_code == center)) if member_ids else []
        by_id = {str(row["id"]): row for row in rows}
        members = []
        for raw_id in external_member_ids:
            row = by_id.get(raw_id)
            if row is None:
                reason = NotificationEligibilityReason.MEMBER_NOT_FOUND
                eligible = False
            elif not row["is_recommended"]:
                reason = NotificationEligibilityReason.MEMBER_NO_LONGER_CANDIDATE
                eligible = False
            else:
                reason = None
                eligible = job_reason is None and expected_job_version == current_version
            members.append(MemberValidationResult(raw_id, eligible, reason))
        if job_reason is None and expected_job_version != current_version:
            job_reason = NotificationEligibilityReason.JOB_VERSION_CHANGED
        return NotificationValidationResult(external_job_id, job_reason is None,
            current_version, job_reason, tuple(members), now, None)

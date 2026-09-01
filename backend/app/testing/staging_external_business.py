"""Staging-only member identity view over the shared fake business gateway."""

from dataclasses import replace

from app.domain.models.external_business import JobSearchQuery
from app.domain.ports.external_business import ExternalBusinessGateway
from app.testing.repositories.staging_liff_links import (
    STAGING_MEMBER_ID,
    InMemoryStagingLiffLinkStore,
)

_FIXTURE_MEMBER_ID = "M001"


class StagingExternalBusinessGateway:
    """Keep fixture data intact while presenting one stable staging member ID."""

    def __init__(
        self,
        delegate: ExternalBusinessGateway,
        link_store: InMemoryStagingLiffLinkStore,
    ) -> None:
        self._delegate = delegate
        self._link_store = link_store

    @staticmethod
    def _to_fixture_member(member_id: str) -> str:
        return _FIXTURE_MEMBER_ID if member_id == STAGING_MEMBER_ID else member_id

    @staticmethod
    def _to_staging_member(member_id: str) -> str:
        return STAGING_MEMBER_ID if member_id == _FIXTURE_MEMBER_ID else member_id

    async def check_link_eligibility(
        self, *, external_organization_id, external_member_id
    ):
        result = await self._delegate.check_link_eligibility(
            external_organization_id=external_organization_id,
            external_member_id=self._to_fixture_member(external_member_id),
        )
        return replace(
            result,
            external_member_id=self._to_staging_member(result.external_member_id),
        )

    async def list_recommended_jobs(
        self, *, external_organization_id, external_member_id
    ):
        return await self._delegate.list_recommended_jobs(
            external_organization_id=external_organization_id,
            external_member_id=self._to_fixture_member(external_member_id),
        )

    async def get_job_detail(self, *, external_organization_id, external_job_id):
        return await self._delegate.get_job_detail(
            external_organization_id=external_organization_id,
            external_job_id=external_job_id,
        )

    async def search_jobs(self, *, external_organization_id, query: JobSearchQuery):
        return await self._delegate.search_jobs(
            external_organization_id=external_organization_id,
            query=query,
        )

    async def list_candidate_members(
        self, *, external_organization_id, external_job_id
    ):
        candidates = await self._delegate.list_candidate_members(
            external_organization_id=external_organization_id,
            external_job_id=external_job_id,
        )
        result = []
        for candidate in candidates:
            member_id = self._to_staging_member(candidate.external_member_id)
            line_subject = candidate.line_subject
            if member_id == STAGING_MEMBER_ID:
                line_subject = self._link_store.subject_for_member(
                    service_id=external_organization_id,
                    member_id=member_id,
                )
            result.append(
                replace(
                    candidate,
                    external_member_id=member_id,
                    line_subject=line_subject,
                )
            )
        return result

    async def validate_notification_targets(
        self,
        *,
        external_organization_id,
        external_job_id,
        expected_job_version,
        external_member_ids,
    ):
        result = await self._delegate.validate_notification_targets(
            external_organization_id=external_organization_id,
            external_job_id=external_job_id,
            expected_job_version=expected_job_version,
            external_member_ids=[
                self._to_fixture_member(member_id) for member_id in external_member_ids
            ],
        )
        return replace(
            result,
            members=tuple(
                replace(
                    member,
                    external_member_id=self._to_staging_member(
                        member.external_member_id
                    ),
                )
                for member in result.members
            ),
        )

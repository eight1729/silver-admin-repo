"""Local-only test doubles allowed by the Admin integration composition."""

from pathlib import Path

from app.domain.models.external_business import PagedExternalJobs
from app.testing.fakes.external_business import FakeExternalBusinessGateway
from app.testing.fixtures.loader import apply_to_fake, load_external_business_scenario
from app.testing.fakes.external_business import NotConfiguredError


_NORMAL_FIXTURE = (
    Path(__file__).parent / "fixtures" / "external_business" / "normal.json"
)


def _build_external_business_fake() -> FakeExternalBusinessGateway:
    scenario = load_external_business_scenario(_NORMAL_FIXTURE)
    if scenario.is_error_scenario:
        raise RuntimeError("local integration fixture must be a normal scenario")

    fake = FakeExternalBusinessGateway()
    apply_to_fake(fake, scenario)
    jobs = scenario.recommended_jobs or []
    fake.search_jobs_result = PagedExternalJobs(
        items=tuple(jobs),
        page=1,
        page_size=20,
        total_count=len(jobs),
        has_next=False,
    )
    if scenario.job_detail is not None:
        fake.job_detail_results = {
            scenario.job_detail.external_job_id: scenario.job_detail
        }
    if scenario.validation_result is not None:
        fake.validation_results = {
            scenario.validation_result.external_job_id: scenario.validation_result
        }
    return fake


class ScopedFakeExternalBusinessGateway:
    """Keep independent Fake business state for each configured organization."""

    def __init__(self, organization_ids) -> None:
        self.gateways = {
            organization_id: _build_external_business_fake()
            for organization_id in dict.fromkeys(organization_ids)
        }

    def _gateway(self, organization_id: str) -> FakeExternalBusinessGateway:
        try:
            return self.gateways[organization_id]
        except KeyError as error:
            raise NotConfiguredError(
                "External Business organization scope is not configured"
            ) from error

    async def check_link_eligibility(self, *, external_organization_id, external_member_id):
        return await self._gateway(external_organization_id).check_link_eligibility(
            external_organization_id=external_organization_id,
            external_member_id=external_member_id,
        )

    async def list_recommended_jobs(self, *, external_organization_id, external_member_id):
        return await self._gateway(external_organization_id).list_recommended_jobs(
            external_organization_id=external_organization_id,
            external_member_id=external_member_id,
        )

    async def get_job_detail(self, *, external_organization_id, external_job_id):
        return await self._gateway(external_organization_id).get_job_detail(
            external_organization_id=external_organization_id,
            external_job_id=external_job_id,
        )

    async def search_jobs(self, *, external_organization_id, query):
        return await self._gateway(external_organization_id).search_jobs(
            external_organization_id=external_organization_id,
            query=query,
        )

    async def list_candidate_members(self, *, external_organization_id, external_job_id):
        return await self._gateway(external_organization_id).list_candidate_members(
            external_organization_id=external_organization_id,
            external_job_id=external_job_id,
        )

    async def validate_notification_targets(
        self,
        *,
        external_organization_id,
        external_job_id,
        expected_job_version,
        external_member_ids,
    ):
        return await self._gateway(external_organization_id).validate_notification_targets(
            external_organization_id=external_organization_id,
            external_job_id=external_job_id,
            expected_job_version=expected_job_version,
            external_member_ids=external_member_ids,
        )


def build_local_integration_external_business(
    scopes=None,
) -> FakeExternalBusinessGateway | ScopedFakeExternalBusinessGateway:
    """Build only the fake business-system boundary used by local integration."""
    if scopes is None:
        return _build_external_business_fake()
    return ScopedFakeExternalBusinessGateway(
        scope.organization_id for scope in scopes
    )

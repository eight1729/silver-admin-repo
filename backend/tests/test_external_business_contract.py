from dataclasses import fields
import inspect
from pathlib import Path
from typing import get_type_hints

import pytest

from app.domain.enums.enums import MemberVerificationStatus as Status
from app.domain.errors.errors import ExternalBusinessNotConfiguredError, ExternalSystemUnavailableError
from app.domain.models.external_business import (
    ExternalJobDetail, ExternalJobSummary, ExternalMemberSummary,
    MemberVerificationInput, MemberVerificationResult,
)
from app.domain.ports.external_business import ExternalBusinessGateway
from app.testing.fakes.external_business import FakeExternalBusinessGateway
from app.testing.local_integration import ScopedFakeExternalBusinessGateway
from app.testing.fixtures.loader import apply_to_fake, load_external_business_scenario


@pytest.mark.parametrize("status", [Status.NO_MATCH, Status.MULTIPLE_MATCH])
def test_non_unique_match_never_exposes_member_id(status):
    assert MemberVerificationResult(status).external_member_id is None
    with pytest.raises(ValueError):
        MemberVerificationResult(status, "stable-id")


@pytest.mark.parametrize("member_id", [None, "", 123])
def test_unique_match_requires_member_id(member_id):
    with pytest.raises(ValueError):
        MemberVerificationResult(Status.UNIQUE_MATCH, member_id)


def test_invalid_status_is_rejected():
    with pytest.raises(ValueError):
        MemberVerificationResult("unknown")


class MemberProviderStub(FakeExternalBusinessGateway):
    async def verify_member(
        self, *, external_organization_id: str, verification: MemberVerificationInput,
    ) -> MemberVerificationResult:
        assert external_organization_id == "org"
        assert verification == MemberVerificationInput("000123", " 山田 太郎 ")
        return MemberVerificationResult(Status.UNIQUE_MATCH, "stable-id")

    async def get_member_summary(
        self, *, external_organization_id: str, external_member_id: str,
    ) -> ExternalMemberSummary:
        assert external_organization_id == "org"
        assert external_member_id == "stable-id"
        return ExternalMemberSummary(external_member_id, None)


@pytest.mark.asyncio
async def test_consumer_uses_returned_id_and_preserves_verification_input():
    gateway: ExternalBusinessGateway = MemberProviderStub()
    verification = MemberVerificationInput("000123", " 山田 太郎 ")
    result = await gateway.verify_member(external_organization_id="org", verification=verification)
    assert result.external_member_id != verification.member_number
    assert result.external_member_id is not None
    summary = await gateway.get_member_summary(
        external_organization_id="org", external_member_id=result.external_member_id,
    )
    assert summary == ExternalMemberSummary("stable-id", None)
    assert {f.name for f in fields(summary)} == {"external_member_id", "display_label"}


@pytest.mark.asyncio
async def test_provider_failure_is_not_a_match_result():
    class FailedProvider(MemberProviderStub):
        async def verify_member(self, **kwargs):
            raise ExternalSystemUnavailableError("unavailable")

    with pytest.raises(ExternalSystemUnavailableError):
        await FailedProvider().verify_member(
            external_organization_id="org", verification=MemberVerificationInput("123", "Name"),
        )


@pytest.mark.parametrize("provider", [FakeExternalBusinessGateway, lambda: ScopedFakeExternalBusinessGateway([])])
@pytest.mark.asyncio
async def test_existing_providers_explicitly_leave_new_capabilities_unconfigured(provider):
    gateway = provider()
    with pytest.raises(ExternalBusinessNotConfiguredError):
        await gateway.verify_member(
            external_organization_id="org", verification=MemberVerificationInput("123", "Name"),
        )
    with pytest.raises(ExternalBusinessNotConfiguredError):
        await gateway.get_member_summary(external_organization_id="org", external_member_id="stable-id")


def test_gateway_signatures_and_provider_compatibility():
    for name in ("verify_member", "get_member_summary", "list_recommended_jobs", "get_job_detail"):
        contract = getattr(ExternalBusinessGateway, name)
        assert inspect.iscoroutinefunction(contract)
        for provider in (FakeExternalBusinessGateway, ScopedFakeExternalBusinessGateway, MemberProviderStub):
            implementation = getattr(provider, name)
            assert inspect.iscoroutinefunction(implementation)
            assert list(inspect.signature(contract).parameters) == list(inspect.signature(implementation).parameters)
        for parameter in list(inspect.signature(contract).parameters.values())[1:]:
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert get_type_hints(ExternalBusinessGateway.verify_member)["return"] is MemberVerificationResult
    assert get_type_hints(ExternalBusinessGateway.get_member_summary)["return"] is ExternalMemberSummary
    assert get_type_hints(ExternalBusinessGateway.list_recommended_jobs)["return"] == list[ExternalJobSummary]
    assert get_type_hints(ExternalBusinessGateway.get_job_detail)["return"] is ExternalJobDetail


@pytest.mark.asyncio
async def test_existing_recommendations_and_detail_keep_domain_models():
    fixture = Path(__file__).parents[1] / "app/testing/fixtures/external_business/normal.json"
    scenario = load_external_business_scenario(fixture)
    gateway = FakeExternalBusinessGateway()
    apply_to_fake(gateway, scenario)
    jobs = await gateway.list_recommended_jobs(external_organization_id="org", external_member_id="member")
    assert jobs and all(isinstance(job, ExternalJobSummary) for job in jobs)
    assert scenario.job_detail is not None
    detail = await gateway.get_job_detail(
        external_organization_id="org", external_job_id=scenario.job_detail.external_job_id,
    )
    assert isinstance(detail, ExternalJobDetail)
    assert detail == scenario.job_detail
    matching = next(job for job in jobs if job.external_job_id == detail.external_job_id)
    assert matching.version == detail.version

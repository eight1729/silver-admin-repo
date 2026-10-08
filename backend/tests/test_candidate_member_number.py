"""Display-only member numbers; UUID selection and provider contracts stay intact."""
from types import SimpleNamespace

import pytest

from app.application.admin_service import AdminApplicationService
from app.api.routes.admin import list_candidates
from test_current_db_external_business import db, M1, J1, NOW
from test_admin_ic_external_business import gateway, json_handler


def application(provider):
    return AdminApplicationService(
        notification_service=None, external_business_gateway=provider,
        demo_service_id=None, line_linked_member_ids=frozenset(),
        scope_resolver=SimpleNamespace(resolve=lambda _: SimpleNamespace(organization_id="org-a")),
    )


@pytest.mark.parametrize("number", ["0007", None])
async def test_current_db_number_reaches_api_without_changing_uuid(db, number):
    provider, engine, tables = db
    engine.connection.execute(tables["members"].update().where(tables["members"].c.id == M1)
                              .values(member_code=number))
    candidates = await provider.list_candidate_members(external_organization_id="org-a", external_job_id=str(J1))
    assert candidates[0].external_member_id == str(M1)
    assert candidates[0].member_number == number
    assert "members.member_code" in str(engine.statements[-1])
    service = application(provider)
    result = await list_candidates(str(J1), SimpleNamespace(service_id="svc"), service)
    assert result[0].model_dump()["member_id"] == str(M1)
    assert result[0].model_dump()["member_number"] == number
    validation = await provider.validate_notification_targets(external_organization_id="org-a",
        external_job_id=str(J1), expected_job_version=NOW.isoformat(), external_member_ids=[str(M1)])
    assert validation.members[0].external_member_id == str(M1)
    assert validation.members[0].eligible


async def test_http_provider_needs_no_new_field_and_keeps_external_identifier():
    provider, calls = gateway(json_handler([dict(external_member_id="external-0007",
        display_label="Member", eligible=True, reason_codes=[], match_rank=None)]))
    try:
        candidates = await provider.list_candidate_members(external_organization_id="org-a", external_job_id="job-1")
        assert candidates[0].external_member_id == "external-0007"
        assert candidates[0].member_number is None
        mapped = application(provider)._candidate(candidates[0])
        async def candidate_result(*args):
            return (mapped,)
        result = await list_candidates("job-1", SimpleNamespace(service_id="svc"),
                                      SimpleNamespace(list_candidates=candidate_result))
        assert result[0].member_id == "external-0007"
        assert result[0].member_number is None
        assert calls[0].url.path == "/v1/orgs/org-a/jobs/job-1/candidate-members"
    finally:
        await provider._client.aclose()

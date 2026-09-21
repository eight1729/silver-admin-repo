"""HTTP external business provider: contract, fail-closed mapping and wiring.

Every request is served by a mock httpx transport; no network and no database.
These tests avoid inspecting FastAPI route internals so they do not drift with
the (unpinned) FastAPI version.
"""

import inspect
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from app.adapter.external_business_http import HttpExternalBusinessGateway
from app.domain.enums.enums import (
    JobStatus,
    MemberVerificationStatus as Status,
    NotificationEligibilityReason as Reason,
)
from app.domain.errors.errors import (
    ExternalBusinessNotConfiguredError,
    ExternalJobNotFoundError,
    ExternalMemberNotFoundError,
    ExternalSystemUnavailableError,
)
from app.domain.models.external_business import JobSearchQuery, MemberVerificationInput
from app.domain.ports.external_business import ExternalBusinessGateway

BASE = "https://business.example.test"
ORG = "organization-a"
VERIFICATION = MemberVerificationInput(member_number="000123", name="Test Member")

JOB_ITEM = {
    "external_job_id": "job-1", "title": "Title", "summary": "Summary",
    "work_location_summary": "Location", "work_schedule_summary": "Schedule",
    "application_deadline": None, "status": "published", "version": "v1",
    "updated_at": "2026-09-20T00:00:00Z", "work_days": "Mon", "work_time": "09:00",
}


def gateway(handler, *, audience=None, environment="local", base_url=BASE):
    """Build the provider over a mock transport. `handler(request) -> Response`."""
    calls = []

    def capture(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    provider = HttpExternalBusinessGateway(
        client=client, base_url=base_url, audience=audience, environment=environment,
    )
    # Never reach the metadata server: the token itself is not under test here.
    provider._token = _fixed_token(provider)
    return provider, calls


def _fixed_token(provider):
    async def token():
        provider.requested_audience = provider._audience
        return "id-token"
    return token


def json_handler(payload, status=200):
    return lambda request: httpx.Response(status, json=payload)


# ---------------------------------------------------------------------------
# Canonical port conformance (the shared contract test only covers Fakes)
# ---------------------------------------------------------------------------
def test_provider_matches_the_canonical_port_signature():
    for name, expected in inspect.getmembers(
        ExternalBusinessGateway, predicate=inspect.isfunction
    ):
        if name.startswith("_"):
            continue
        actual = getattr(HttpExternalBusinessGateway, name, None)
        assert actual is not None, f"{name} is missing from the HTTP provider"
        assert inspect.iscoroutinefunction(actual), f"{name} must be async"

        # eval_str resolves the provider's `from __future__ import annotations`
        # strings, so the comparison is on types rather than on spelling.
        want = inspect.signature(expected, eval_str=True)
        got = inspect.signature(actual, eval_str=True)
        assert list(want.parameters) == list(got.parameters), f"{name} parameter names differ"
        for parameter in want.parameters.values():
            if parameter.name == "self":
                continue
            mine = got.parameters[parameter.name]
            assert mine.kind is inspect.Parameter.KEYWORD_ONLY, f"{name}.{parameter.name}"
            assert mine.annotation == parameter.annotation, f"{name}.{parameter.name} annotation"
        assert got.return_annotation == want.return_annotation, f"{name} return annotation"


def test_id_token_dependencies_are_actually_installed():
    # google-auth does not depend on requests, and the transport imports it
    # lazily, so a missing dependency would only surface at runtime.
    from google.auth.transport.requests import Request  # noqa: F401
    from google.oauth2 import id_token  # noqa: F401


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", [None, "", " ", "ftp://host", "https://user@host",
                                   "https://host?a=b", "https://host#f", "not-a-url"])
def test_invalid_base_url_is_a_configuration_error(value):
    with pytest.raises(ExternalBusinessNotConfiguredError):
        HttpExternalBusinessGateway(client=httpx.AsyncClient(), base_url=value)


def test_production_refuses_plaintext_http():
    with pytest.raises(ExternalBusinessNotConfiguredError):
        HttpExternalBusinessGateway(
            client=httpx.AsyncClient(), base_url="http://business.example.test",
            environment="production",
        )
    # Other environments may use plaintext HTTP for a local provider.
    HttpExternalBusinessGateway(
        client=httpx.AsyncClient(), base_url="http://business.example.test",
        environment="local",
    )


def assert_sent_to_base(request: httpx.Request):
    # Compare the origin, not a string prefix: "https://business.example.test.evil"
    # starts with the base URL but is a different host.
    assert (request.url.scheme, request.url.host, request.url.port) == (
        httpx.URL(BASE).scheme, httpx.URL(BASE).host, httpx.URL(BASE).port
    )


async def test_audience_is_configurable_and_the_destination_stays_the_base_url():
    provider, calls = gateway(json_handler(JOB_ITEM), audience="https://audience.example.test")
    await provider.get_job_detail(external_organization_id=ORG, external_job_id="job-1")
    assert provider.requested_audience == "https://audience.example.test"
    assert_sent_to_base(calls[0])


async def test_audience_defaults_to_the_base_url():
    provider, calls = gateway(json_handler(JOB_ITEM))
    await provider.get_job_detail(external_organization_id=ORG, external_job_id="job-1")
    assert provider.requested_audience == BASE
    assert_sent_to_base(calls[0])


# ---------------------------------------------------------------------------
# Member verification
# ---------------------------------------------------------------------------
async def test_verify_member_maps_a_unique_match():
    provider, calls = gateway(json_handler(
        {"eligible": True, "external_member_id": "900001",
         "display_label": "Display", "reason_code": None}
    ))
    result = await provider.verify_member(
        external_organization_id=ORG, verification=VERIFICATION
    )
    assert result.status is Status.UNIQUE_MATCH
    assert result.external_member_id == "900001"
    # The member number travels in the body, never in the path.
    assert "000123" not in str(calls[0].url)
    assert calls[0].url.path == f"/v1/orgs/{ORG}/members:verify"


async def test_verify_member_maps_a_false_flag_to_no_match_without_an_id():
    provider, _ = gateway(json_handler(
        {"eligible": False, "external_member_id": None,
         "display_label": None, "reason_code": "not_matched"}
    ))
    result = await provider.verify_member(
        external_organization_id=ORG, verification=VERIFICATION
    )
    assert result.status is Status.NO_MATCH
    assert result.external_member_id is None


async def test_verify_member_never_reports_a_multiple_match():
    # The provider keys members by member number, so more than one is impossible.
    provider, _ = gateway(json_handler(
        {"eligible": True, "external_member_id": "900001", "reason_code": None}
    ))
    result = await provider.verify_member(
        external_organization_id=ORG, verification=VERIFICATION
    )
    assert result.status is not Status.MULTIPLE_MATCH


@pytest.mark.parametrize("payload", [
    {"external_member_id": "900001"},                       # eligible missing
    {"eligible": "true", "external_member_id": "900001"},   # eligible not a bool
    {"eligible": 1, "external_member_id": "900001"},
    {"eligible": None, "external_member_id": "900001"},
    {"eligible": True, "external_member_id": ""},           # match without an id
    {"eligible": True, "external_member_id": None},
    {"eligible": True, "external_member_id": 900001},
])
async def test_verify_member_never_folds_a_broken_response_into_a_match_outcome(payload):
    provider, _ = gateway(json_handler(payload))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.verify_member(
            external_organization_id=ORG, verification=VERIFICATION
        )


async def test_verify_member_treats_rate_limiting_as_unavailable():
    # The provider answers 429 with a *complete, well-formed* verification body,
    # so only the status code separates "too many attempts" from "not this
    # person". Reading the body would turn throttling into a match outcome and
    # tell the user they are not a member.
    provider, _ = gateway(json_handler(
        {"eligible": False, "external_member_id": None, "display_label": None,
         "reason_code": "rate_limited"},
        status=429,
    ))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.verify_member(
            external_organization_id=ORG, verification=VERIFICATION
        )


async def test_a_throttled_job_read_is_not_an_empty_result():
    # Same shape for job reads: a 429 carrying a usable body must not be mapped.
    provider, _ = gateway(json_handler(
        dict(JOB_ITEM, description="", required_conditions=[]), status=429
    ))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.get_job_detail(external_organization_id=ORG, external_job_id="job-1")


# ---------------------------------------------------------------------------
# Member summary and recommended jobs
# ---------------------------------------------------------------------------
async def test_get_member_summary_maps_the_display_projection():
    provider, calls = gateway(json_handler(
        {"external_member_id": "900001", "display_label": "Display"}
    ))
    summary = await provider.get_member_summary(
        external_organization_id=ORG, external_member_id="900001"
    )
    assert (summary.external_member_id, summary.display_label) == ("900001", "Display")
    assert calls[0].url.path == f"/v1/orgs/{ORG}/members:summary"
    assert "900001" not in str(calls[0].url)


async def test_get_member_summary_accepts_a_null_display_label():
    provider, _ = gateway(json_handler(
        {"external_member_id": "900001", "display_label": None}
    ))
    summary = await provider.get_member_summary(
        external_organization_id=ORG, external_member_id="900001"
    )
    assert summary.display_label is None


async def test_get_member_summary_maps_a_missing_member_to_not_found():
    provider, _ = gateway(json_handler({"error": "member_not_found"}, status=404))
    with pytest.raises(ExternalMemberNotFoundError):
        await provider.get_member_summary(
            external_organization_id=ORG, external_member_id="900001"
        )


@pytest.mark.parametrize("payload", [
    {"display_label": "Display"},                       # identifier missing
    {"external_member_id": "", "display_label": None},
    {"external_member_id": 900001},
])
async def test_get_member_summary_rejects_a_missing_identifier(payload):
    provider, _ = gateway(json_handler(payload))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.get_member_summary(
            external_organization_id=ORG, external_member_id="900001"
        )


async def test_list_recommended_jobs_maps_items():
    provider, calls = gateway(json_handler({"items": [JOB_ITEM]}))
    jobs = await provider.list_recommended_jobs(
        external_organization_id=ORG, external_member_id="900001"
    )
    assert [job.external_job_id for job in jobs] == ["job-1"]
    assert jobs[0].status is JobStatus.PUBLISHED
    assert jobs[0].version == "v1"
    assert calls[0].url.path == f"/v1/orgs/{ORG}/members:recommended-jobs"
    assert "900001" not in str(calls[0].url)


async def test_list_recommended_jobs_maps_an_empty_list_to_no_recommendations():
    provider, _ = gateway(json_handler({"items": []}))
    assert await provider.list_recommended_jobs(
        external_organization_id=ORG, external_member_id="900001"
    ) == []


async def test_list_recommended_jobs_maps_a_missing_member_to_not_found():
    provider, _ = gateway(json_handler({"error": "member_not_found"}, status=404))
    with pytest.raises(ExternalMemberNotFoundError):
        await provider.list_recommended_jobs(
            external_organization_id=ORG, external_member_id="900001"
        )


@pytest.mark.parametrize("payload", [
    {},                                                     # items missing
    {"items": {}},                                          # items not a list
    {"items": ["not-an-object"]},
    {"items": [dict(JOB_ITEM, version=None)]},              # version missing
    {"items": [dict(JOB_ITEM, version="")]},
    {"items": [dict(JOB_ITEM, external_job_id="")]},
])
async def test_list_recommended_jobs_rejects_a_semantically_broken_page(payload):
    provider, _ = gateway(json_handler(payload))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.list_recommended_jobs(
            external_organization_id=ORG, external_member_id="900001"
        )


async def test_link_eligibility_is_not_configured():
    provider, _ = gateway(json_handler({}))
    with pytest.raises(ExternalBusinessNotConfiguredError):
        await provider.check_link_eligibility(
            external_organization_id=ORG, external_member_id="900001"
        )


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
async def test_search_jobs_maps_a_page_and_sends_the_query():
    provider, calls = gateway(json_handler(
        {"items": [JOB_ITEM], "page": 2, "page_size": 5, "total_count": 9, "has_next": True}
    ))
    page = await provider.search_jobs(
        external_organization_id=ORG,
        query=JobSearchQuery(keyword="word", statuses=(JobStatus.PUBLISHED,), page=2, page_size=5),
    )
    assert (page.page, page.page_size, page.total_count, page.has_next) == (2, 5, 9, True)
    assert page.items[0].external_job_id == "job-1"
    params = calls[0].url.params
    assert (params["keyword"], params["statuses"], params["page"]) == ("word", "published", "2")


async def test_search_jobs_does_not_page_past_the_end_on_a_missing_flag():
    provider, _ = gateway(json_handler({"items": []}))
    page = await provider.search_jobs(external_organization_id=ORG, query=JobSearchQuery())
    assert page.has_next is False


async def test_get_job_detail_maps_the_detail():
    provider, _ = gateway(json_handler({
        "external_job_id": "job-1", "title": "Title", "description": "Body",
        "work_location": "Location", "work_schedule_text": "Schedule",
        "application_deadline": None, "required_conditions": [], "status": "published",
        "version": "v1", "updated_at": "2026-09-20T00:00:00Z",
        "staff_notes": None, "job_url": None,
    }))
    detail = await provider.get_job_detail(external_organization_id=ORG, external_job_id="job-1")
    assert (detail.external_job_id, detail.version) == ("job-1", "v1")
    assert detail.required_conditions == ()


async def test_get_job_detail_maps_a_missing_job_to_not_found():
    provider, _ = gateway(json_handler({"error": "job_not_found"}, status=404))
    with pytest.raises(ExternalJobNotFoundError):
        await provider.get_job_detail(external_organization_id=ORG, external_job_id="job-1")


async def test_get_job_detail_rejects_a_response_for_another_job():
    provider, _ = gateway(json_handler(dict(JOB_ITEM, external_job_id="job-9",
                                            description="", required_conditions=[])))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.get_job_detail(external_organization_id=ORG, external_job_id="job-1")


async def test_list_candidate_members_maps_rows_and_drops_the_line_subject():
    provider, _ = gateway(json_handler([{
        "external_member_id": "900001", "display_label": "Display", "eligible": True,
        "reason_codes": [], "match_rank": 1, "line_subject": "U-leaked",
        "preference_summary": "Summary",
    }]))
    rows = await provider.list_candidate_members(
        external_organization_id=ORG, external_job_id="job-1"
    )
    assert rows[0].external_member_id == "900001"
    assert rows[0].match_rank == 1
    # A LINE subject must never enter the Admin domain, even when offered.
    assert rows[0].line_subject is None


@pytest.mark.parametrize("row", [
    {"external_member_id": "900001", "reason_codes": []},                    # eligible missing
    {"external_member_id": "900001", "eligible": "true", "reason_codes": []},
    {"external_member_id": "900001", "eligible": True, "reason_codes": ["member_inactive"]},
    {"external_member_id": "900001", "eligible": True},                      # reason_codes missing
    {"external_member_id": "", "eligible": True, "reason_codes": []},
])
async def test_list_candidate_members_rejects_a_semantically_broken_row(row):
    provider, _ = gateway(json_handler([row]))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.list_candidate_members(
            external_organization_id=ORG, external_job_id="job-1"
        )


async def test_list_candidate_members_rejects_a_non_list_body():
    provider, _ = gateway(json_handler({"rows": []}))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.list_candidate_members(
            external_organization_id=ORG, external_job_id="job-1"
        )


VALIDATION = {
    "external_job_id": "job-1", "job_eligible": True, "current_job_version": "v1",
    "job_reason_code": None,
    "members": [{"external_member_id": "900001", "eligible": True, "reason_code": None}],
    "validated_at": "2026-09-20T00:00:00Z", "external_request_id": None,
}


async def test_validate_notification_targets_maps_the_result():
    provider, _ = gateway(json_handler(VALIDATION))
    result = await provider.validate_notification_targets(
        external_organization_id=ORG, external_job_id="job-1",
        expected_job_version="v1", external_member_ids=["900001"],
    )
    assert result.job_eligible is True
    assert result.job_reason_code is None
    assert result.members[0].eligible is True


async def test_validate_notification_targets_keeps_an_ineligible_reason():
    provider, _ = gateway(json_handler(dict(
        VALIDATION, job_eligible=False, job_reason_code="job_closed",
        members=[{"external_member_id": "900001", "eligible": False,
                  "reason_code": "member_inactive"}],
    )))
    result = await provider.validate_notification_targets(
        external_organization_id=ORG, external_job_id="job-1",
        expected_job_version="v1", external_member_ids=["900001"],
    )
    assert result.job_reason_code is Reason.JOB_CLOSED
    assert result.members[0].reason_code is Reason.MEMBER_INACTIVE


@pytest.mark.parametrize("payload", [
    dict(VALIDATION, job_eligible="true"),                       # not a bool
    {k: v for k, v in VALIDATION.items() if k != "job_eligible"},
    dict(VALIDATION, job_reason_code="job_closed"),              # eligible with a reason
    dict(VALIDATION, external_job_id="job-9"),                   # another job
    dict(VALIDATION, external_job_id=""),
    dict(VALIDATION, validated_at=None),                         # no timestamp
    dict(VALIDATION, members={}),                                # not a list
    dict(VALIDATION, members=["not-an-object"]),
    dict(VALIDATION, members=[{"external_member_id": "900001", "eligible": True,
                               "reason_code": "member_inactive"}]),
    dict(VALIDATION, members=[{"external_member_id": "900001"}]),
    dict(VALIDATION, members=[{"external_member_id": "", "eligible": True,
                               "reason_code": None}]),
])
async def test_validate_notification_targets_rejects_a_semantically_broken_result(payload):
    provider, _ = gateway(json_handler(payload))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.validate_notification_targets(
            external_organization_id=ORG, external_job_id="job-1",
            expected_job_version="v1", external_member_ids=["900001"],
        )


async def test_an_absent_job_may_report_an_empty_current_version():
    provider, _ = gateway(json_handler(dict(
        VALIDATION, job_eligible=False, job_reason_code="job_not_found",
        current_job_version="", members=[],
    )))
    result = await provider.validate_notification_targets(
        external_organization_id=ORG, external_job_id="job-1",
        expected_job_version="v1", external_member_ids=[],
    )
    assert result.current_job_version == ""


# ---------------------------------------------------------------------------
# Transport-level failures
# ---------------------------------------------------------------------------
# A complete, usable detail body. Pairing it with a non-success status means
# only the status code can produce the failure: an implementation that read the
# body and ignored the status would return a result and redden these tests.
DETAIL = dict(JOB_ITEM, description="Body", work_location="Location",
              work_schedule_text="Schedule", required_conditions=[],
              staff_notes=None, job_url=None)


def _call(provider):
    return provider.get_job_detail(external_organization_id=ORG, external_job_id="job-1")


@pytest.mark.parametrize("status", [301, 302, 307, 400, 422, 429, 500, 502, 503])
async def test_only_a_success_status_is_read_as_an_answer(status):
    provider, _ = gateway(json_handler(DETAIL, status=status))
    with pytest.raises(ExternalSystemUnavailableError):
        await _call(provider)


@pytest.mark.parametrize("status", [401, 403])
async def test_a_rejected_caller_is_never_shown_as_a_business_outcome(status):
    provider, _ = gateway(json_handler(DETAIL, status=status))
    with pytest.raises(ExternalSystemUnavailableError):
        await _call(provider)


async def test_an_unserved_organization_is_a_configuration_failure_not_a_missing_job():
    # The provider answers 404 for both an unknown job and an organization it does
    # not serve. A scope mismatch must not read as "this job does not exist".
    provider, _ = gateway(json_handler({"error": "organization_not_found"}, status=404))
    with pytest.raises(ExternalSystemUnavailableError):
        await _call(provider)


async def test_an_unparsable_body_is_unavailable():
    provider, _ = gateway(lambda request: httpx.Response(200, content=b"{not json"))
    with pytest.raises(ExternalSystemUnavailableError):
        await _call(provider)


@pytest.mark.parametrize("error", [
    httpx.ConnectTimeout("timeout"), httpx.ReadTimeout("timeout"),
    httpx.ConnectError("refused"),
    # Not only timeouts and network errors: a misbehaving peer or proxy must not
    # escape as a generic exception and become a 500 instead of an outage.
    httpx.RemoteProtocolError("bad peer"), httpx.ProxyError("bad proxy"),
])
async def test_transport_failures_are_unavailable(error):
    def raising(request):
        raise error
    provider, _ = gateway(raising)
    with pytest.raises(ExternalSystemUnavailableError):
        await _call(provider)


# ---------------------------------------------------------------------------
# Wiring: both entrypoints must share one provider instance
# ---------------------------------------------------------------------------
def admin_settings_for(monkeypatch, **overrides):
    from pydantic_settings import DotEnvSettingsSource
    monkeypatch.setattr(DotEnvSettingsSource, "_read_env_files", lambda self: {})
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/unused")
    monkeypatch.setenv("APP_ENV", "test")
    from app.core.settings_admin import AdminSettings

    overrides.setdefault("app_env", "test")
    return AdminSettings(
        _env_file=None, database_url="postgresql://unused/unused",
        admin_internal_api_bearer_token=SecretStr("test-incoming"),
        admin_internal_api_scopes={"service-a": ORG},
        current_db_business_centers={ORG: "center-a"},
        admin_notification_runner_service_ids="service-a",
        admin_line_internal_api_base_url="https://line.internal",
        admin_line_internal_api_bearer_token=SecretStr("test-outgoing"),
        **overrides,
    )


def build_app(monkeypatch, **overrides):
    monkeypatch.setattr("app.db.engine.get_engine", lambda: SimpleNamespace(name="engine"))
    from app.main_admin import create_admin_app

    return create_admin_app(admin_settings_for(monkeypatch, **overrides))


def test_the_configured_provider_reaches_both_entrypoints(monkeypatch):
    app = build_app(monkeypatch, admin_external_business_base_url=BASE)

    internal = app.state.admin_internal_business_gateway
    staff = app.state.admin_runtime_composition.external_business
    assert isinstance(internal, HttpExternalBusinessGateway)
    # Identity, not type: two separate instances would also both be HTTP while
    # still being a split, and a type check would not notice.
    assert staff is internal


def test_without_the_setting_both_entrypoints_stay_on_the_current_db(monkeypatch):
    from app.adapter.current_db_external_business import CurrentDbExternalBusinessGateway

    app = build_app(monkeypatch)

    # None makes the Internal API dependency build the Current DB gateway itself.
    assert app.state.admin_internal_business_gateway is None
    assert isinstance(
        app.state.admin_runtime_composition.external_business,
        CurrentDbExternalBusinessGateway,
    )


def test_an_injected_gateway_still_wins_over_the_setting(monkeypatch):
    sentinel = object()
    monkeypatch.setattr("app.db.engine.get_engine", lambda: SimpleNamespace(name="engine"))
    from app.main_admin import create_admin_app

    app = create_admin_app(
        admin_settings_for(monkeypatch, admin_external_business_base_url=BASE),
        external_business_gateway=sentinel,
    )
    assert app.state.admin_internal_business_gateway is sentinel


async def test_the_internal_api_reads_through_the_configured_provider(monkeypatch):
    """The Internal API must reach the external system, not the Current DB."""
    from app.api.admin_internal_deps import get_admin_internal_service
    from starlette.requests import Request

    app = build_app(monkeypatch, admin_external_business_base_url=BASE)
    provider = app.state.admin_internal_business_gateway

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"external_member_id": "900001",
                                         "display_label": "Display"})

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider._token = _fixed_token(provider)

    service = get_admin_internal_service(Request({"type": "http", "app": app}), None)
    summary = await service.get_member_summary("service-a", "900001")
    assert summary.external_member_id == "900001"
    assert seen == [f"/v1/orgs/{ORG}/members:summary"]


# ---------------------------------------------------------------------------
# Review findings (2026-09-21): each case reproduces a behaviour that was
# accepted before the fix.
# ---------------------------------------------------------------------------
async def test_verify_member_rejects_a_match_that_carries_a_mismatch_reason():
    # Previously accepted as UNIQUE_MATCH: `eligible` and the ID were read while
    # `reason_code` was never looked at, so a contradictory response became a
    # confirmed identity.
    provider, _ = gateway(json_handler(
        {"eligible": True, "external_member_id": "900001",
         "display_label": "Display", "reason_code": "not_matched"}
    ))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.verify_member(
            external_organization_id=ORG, verification=VERIFICATION
        )


async def test_validate_notification_targets_rejects_a_duplicated_member():
    # NotificationService keys validation rows by member ID, so a second row for
    # the same member silently wins. An ineligible row followed by an eligible
    # one would end up sending to a member who must not be contacted.
    provider, _ = gateway(json_handler(dict(VALIDATION, members=[
        {"external_member_id": "900001", "eligible": False, "reason_code": "member_inactive"},
        {"external_member_id": "900001", "eligible": True, "reason_code": None},
    ])))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.validate_notification_targets(
            external_organization_id=ORG, external_job_id="job-1",
            expected_job_version="v1", external_member_ids=["900001"],
        )


@pytest.mark.parametrize("payload", [
    {k: v for k, v in VALIDATION.items() if k != "current_job_version"},
    dict(VALIDATION, current_job_version=None),
    dict(VALIDATION, current_job_version=1),
    # Eligible without a version defeats the staleness check entirely.
    dict(VALIDATION, current_job_version=""),
])
async def test_validate_notification_targets_requires_a_usable_current_version(payload):
    provider, _ = gateway(json_handler(payload))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.validate_notification_targets(
            external_organization_id=ORG, external_job_id="job-1",
            expected_job_version="v1", external_member_ids=["900001"],
        )


@pytest.mark.parametrize("job_id", ["..", ".", ""])
async def test_a_job_identifier_that_cannot_be_a_path_segment_names_no_job(job_id):
    # `quote()` leaves dot segments intact and the client then resolves them, so
    # `/jobs/..` was sent to `/v1/orgs/{org}` - a different endpoint than the one
    # the caller asked for.
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json=DETAIL)

    provider, _ = gateway(handler)
    with pytest.raises(ExternalJobNotFoundError):
        await provider.get_job_detail(external_organization_id=ORG, external_job_id=job_id)
    assert seen == [], "a request was sent for an unusable job identifier"


@pytest.mark.parametrize("org", ["..", ".", ""])
async def test_an_organization_identifier_that_cannot_be_a_path_segment_is_not_configured(org):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json=DETAIL)

    provider, _ = gateway(handler)
    with pytest.raises(ExternalBusinessNotConfiguredError):
        await provider.get_job_detail(external_organization_id=org, external_job_id="job-1")
    assert seen == []


def test_local_integration_also_receives_the_configured_provider(monkeypatch):
    # APP_ENV=local with local integration mode is a valid combination, and it
    # took a different composition branch that never saw the provider: the
    # Internal API would read the external system while local integration read
    # the Current DB.
    monkeypatch.setattr("app.db.engine.get_engine", lambda: SimpleNamespace(name="engine"))
    from app.main_admin import create_admin_app

    settings = admin_settings_for(
        monkeypatch,
        app_env="local",
        admin_local_integration_mode=True,
        admin_local_integration_scopes={"service-a": ORG},
        admin_external_business_base_url=BASE,
    )
    app = create_admin_app(settings)

    internal = app.state.admin_internal_business_gateway
    assert isinstance(internal, HttpExternalBusinessGateway)
    assert app.state.admin_local_integration.external_business is internal


# ---------------------------------------------------------------------------
# Second review round (2026-09-21)
# ---------------------------------------------------------------------------
async def test_list_candidate_members_rejects_a_duplicated_member():
    # The same last-wins hazard as the validation rows, on the sibling path:
    # NotificationService keys candidates by member ID too.
    provider, _ = gateway(json_handler([
        {"external_member_id": "900001", "display_label": "A", "eligible": False,
         "reason_codes": ["member_inactive"], "match_rank": 1},
        {"external_member_id": "900001", "display_label": "A", "eligible": True,
         "reason_codes": [], "match_rank": 2},
    ]))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.list_candidate_members(
            external_organization_id=ORG, external_job_id="job-1"
        )


async def test_get_member_summary_rejects_a_summary_for_another_member():
    # The port defines this as the projection of the *requested* member. Showing
    # 900002's name in answer to a question about 900001 is a wrong answer about
    # a person, not a missing one.
    provider, _ = gateway(json_handler(
        {"external_member_id": "900002", "display_label": "Someone else"}
    ))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.get_member_summary(
            external_organization_id=ORG, external_member_id="900001"
        )


@pytest.mark.parametrize("call", [
    "get_job_detail", "list_candidate_members", "validate_notification_targets",
])
async def test_every_job_path_refuses_an_unusable_job_identifier(call):
    # Reverting any one path to the organization-flavoured escape would otherwise
    # go unnoticed: only get_job_detail was covered.
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json=DETAIL)

    provider, _ = gateway(handler)
    kwargs = {"external_organization_id": ORG, "external_job_id": ".."}
    if call == "validate_notification_targets":
        kwargs |= {"expected_job_version": "v1", "external_member_ids": []}
    with pytest.raises(ExternalJobNotFoundError):
        await getattr(provider, call)(**kwargs)
    assert seen == []


@pytest.mark.parametrize("payload", [
    dict(VALIDATION, job_eligible=False, job_reason_code="job_closed",
         current_job_version=None, members=[]),
    dict(VALIDATION, job_eligible=False, job_reason_code="job_closed",
         current_job_version=1, members=[]),
])
async def test_the_current_version_is_typed_even_when_the_job_is_not_eligible(payload):
    # The empty-string allowance applies only to an absent job; it is not a
    # licence to accept a missing or non-string field whenever eligible is false.
    provider, _ = gateway(json_handler(payload))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.validate_notification_targets(
            external_organization_id=ORG, external_job_id="job-1",
            expected_job_version="v1", external_member_ids=[],
        )


@pytest.mark.parametrize("value", [
    "https://bad host", "https://host\tname", "https://host\nname",
])
def test_a_base_url_with_whitespace_fails_at_configuration_time(value):
    # Neither urlsplit nor httpx.URL rejects these, so without this check a typo
    # in configuration would surface much later as an apparent outage.
    with pytest.raises(ExternalBusinessNotConfiguredError):
        HttpExternalBusinessGateway(client=httpx.AsyncClient(), base_url=value)


# ---------------------------------------------------------------------------
# Third review round (2026-09-21): the same hazards on the remaining paths
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("call,payload", [
    ("search_jobs", {"items": [JOB_ITEM, dict(JOB_ITEM, work_time="18:00", version="v2")]}),
    ("list_recommended_jobs", {"items": [JOB_ITEM, dict(JOB_ITEM, work_time="18:00")]}),
])
async def test_a_repeated_job_is_refused_on_every_list(call, payload):
    # Callers look a job up by ID and take the first match, so a second row with
    # different hours would build a notification from the stale one.
    provider, _ = gateway(json_handler(payload))
    kwargs = ({"query": JobSearchQuery()} if call == "search_jobs"
              else {"external_member_id": "900001"})
    with pytest.raises(ExternalSystemUnavailableError):
        await getattr(provider, call)(external_organization_id=ORG, **kwargs)


@pytest.mark.parametrize("members", [
    # Answered about somebody who was not asked about.
    [{"external_member_id": "900002", "eligible": True, "reason_code": None}],
    # Asked about two, answered about one: the missing one would be reported to
    # an operator as a member that does not exist.
    [{"external_member_id": "900001", "eligible": True, "reason_code": None}],
    [],
])
async def test_validation_must_answer_exactly_the_members_asked_about(members):
    provider, _ = gateway(json_handler(dict(VALIDATION, members=members)))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.validate_notification_targets(
            external_organization_id=ORG, external_job_id="job-1",
            expected_job_version="v1", external_member_ids=["900001", "900002"],
        )


async def test_validation_accepts_exactly_the_requested_members():
    provider, _ = gateway(json_handler(dict(VALIDATION, members=[
        {"external_member_id": "900002", "eligible": False, "reason_code": "member_inactive"},
        {"external_member_id": "900001", "eligible": True, "reason_code": None},
    ])))
    result = await provider.validate_notification_targets(
        external_organization_id=ORG, external_job_id="job-1",
        expected_job_version="v1", external_member_ids=["900001", "900002"],
    )
    assert {row.external_member_id for row in result.members} == {"900001", "900002"}


async def test_only_an_absent_job_may_omit_the_current_version():
    # A closed job with no version reads downstream as a version change.
    provider, _ = gateway(json_handler(dict(
        VALIDATION, job_eligible=False, job_reason_code="job_closed",
        current_job_version="", members=[],
    )))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.validate_notification_targets(
            external_organization_id=ORG, external_job_id="job-1",
            expected_job_version="v1", external_member_ids=[],
        )


@pytest.mark.parametrize("value", ["https://:443", "https://host\x7fname"])
def test_a_base_url_without_a_host_or_with_a_control_character_is_refused(value):
    with pytest.raises(ExternalBusinessNotConfiguredError):
        HttpExternalBusinessGateway(client=httpx.AsyncClient(), base_url=value)


@pytest.mark.parametrize("value", [
    "https://[2001:db8::1]:8443", "https://host.example:8443/base",
    "https://xn--eckwd4c7c.example", "https://host.example/a%20b",
])
def test_ordinary_urls_are_still_accepted(value):
    # The whitespace and host checks must not reject IPv6 literals, ports,
    # punycode, or percent-encoded paths.
    HttpExternalBusinessGateway(client=httpx.AsyncClient(), base_url=value)


@pytest.mark.parametrize("configured,expect_provider", [
    (None, False), ("", False),
    # A whitespace-only or padded value is a misconfiguration, not "unset":
    # silently falling back would switch the data source without saying so.
    (" ", None), ("  https://business.example.test  ", None),
])
def test_a_misconfigured_base_url_fails_instead_of_selecting_another_source(
    monkeypatch, configured, expect_provider
):
    monkeypatch.setattr("app.db.engine.get_engine", lambda: SimpleNamespace(name="engine"))
    from app.main_admin import create_admin_app

    settings = admin_settings_for(monkeypatch, admin_external_business_base_url=configured)
    if expect_provider is None:
        with pytest.raises(ExternalBusinessNotConfiguredError):
            create_admin_app(settings)
        return
    app = create_admin_app(settings)
    assert (app.state.admin_internal_business_gateway is not None) is expect_provider


@pytest.mark.parametrize("version", [None, 123, []])
async def test_an_absent_job_still_has_to_report_a_string_version(version):
    # The empty-string allowance is for an absent job, but the value must still
    # be a string: a number silently becoming "" would hide a contract break,
    # and only this combination exercises the type check on its own.
    provider, _ = gateway(json_handler(dict(
        VALIDATION, job_eligible=False, job_reason_code="job_not_found",
        current_job_version=version, members=[],
    )))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.validate_notification_targets(
            external_organization_id=ORG, external_job_id="job-1",
            expected_job_version="v1", external_member_ids=[],
        )


async def test_an_absent_job_reports_an_empty_string_version():
    provider, _ = gateway(json_handler(dict(
        VALIDATION, job_eligible=False, job_reason_code="job_not_found",
        current_job_version="", members=[],
    )))
    result = await provider.validate_notification_targets(
        external_organization_id=ORG, external_job_id="job-1",
        expected_job_version="v1", external_member_ids=[],
    )
    assert result.current_job_version == ""

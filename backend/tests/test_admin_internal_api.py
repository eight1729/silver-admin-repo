import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from app.api.routes.admin_internal import router
from app.domain.enums.enums import MemberVerificationStatus as Status
from app.domain.errors.errors import (
    ExternalBusinessNotConfiguredError, ExternalMemberNotFoundError,
    ExternalSystemUnavailableError,
)
from app.domain.models.external_business import ExternalMemberSummary, MemberVerificationResult
from app.testing.fakes.external_business import FakeExternalBusinessGateway
from app.testing.fixtures.loader import apply_to_fake, load_external_business_scenario
from scripts.export_admin_internal_openapi import OUTPUT, serialize


class Provider(FakeExternalBusinessGateway):
    def __init__(self):
        super().__init__()
        self.status = Status.UNIQUE_MATCH
        self.error = None
        self.member_calls = []

    async def verify_member(self, *, external_organization_id, verification):
        self.member_calls.append((external_organization_id, verification))
        if self.error:
            raise self.error
        return MemberVerificationResult(
            self.status, "stable-member" if self.status is Status.UNIQUE_MATCH else None,
        )

    async def get_member_summary(self, *, external_organization_id, external_member_id):
        self.member_calls.append((external_organization_id, external_member_id))
        if self.error:
            raise self.error
        return ExternalMemberSummary(external_member_id, "Display")


@pytest.fixture
def context():
    app = FastAPI()
    app.include_router(router)
    provider = Provider()
    app.state.admin_runtime_settings = SimpleNamespace(
        admin_internal_api_bearer_token=SecretStr("test-incoming"),
        admin_line_internal_api_bearer_token=SecretStr("test-outgoing"),
        admin_internal_api_scopes={"service-a": "organization-a", "service-b": "organization-b"},
    )
    app.state.admin_internal_business_gateway = provider
    return app, provider


async def post(context, path="members:verify", body=None, authorization="Bearer test-incoming"):
    app, _ = context
    headers = {} if authorization is None else {"Authorization": authorization}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://admin") as client:
        return await client.post(
            f"/internal/v1/{path}", headers=headers,
            json=body if body is not None else {
                "service_id": "service-a", "member_number": "000123", "name": " 山田 太郎 ",
            },
        )


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Basic test-incoming", "Bearer test-outgoing", "Bearer staff-oidc"])
async def test_authentication_failures_do_not_call_provider(context, authorization):
    response = await post(context, authorization=authorization)
    assert response.status_code == 401
    assert response.json() == {"detail": {"error": "authentication_failed"}}
    assert response.headers["www-authenticate"] == "Bearer"
    assert not context[1].member_calls


@pytest.mark.parametrize("secret", [None, "", " ", "bad token", "token\n"])
async def test_missing_or_malformed_auth_configuration_fails_closed(context, secret):
    context[0].state.admin_runtime_settings.admin_internal_api_bearer_token = (
        None if secret is None else SecretStr(secret)
    )
    response = await post(context)
    assert response.status_code == 503
    assert response.json() == {"detail": {"error": "authentication_unavailable"}}
    assert not context[1].member_calls


@pytest.mark.parametrize("status", list(Status))
async def test_verification_outcomes(context, status):
    context[1].status = status
    response = await post(context)
    assert response.status_code == 200
    expected = {"status": status.value}
    if status is Status.UNIQUE_MATCH:
        expected["external_member_id"] = "stable-member"
    assert response.json() == expected
    organization, verification = context[1].member_calls[0]
    assert organization == "organization-a"
    assert verification.member_number == "000123"
    assert verification.name == " 山田 太郎 "


@pytest.mark.parametrize("service", ["unknown", " service-a", "organization-a"])
async def test_unknown_scope_fails_closed(context, service):
    response = await post(context, body={"service_id": service, "member_number": "123", "name": "Name"})
    assert response.status_code == 403
    assert response.json() == {"detail": {"error": "scope_forbidden"}}
    assert not context[1].member_calls


async def test_invalid_configured_scope_fails_closed(context):
    context[0].state.admin_runtime_settings.admin_internal_api_scopes = {"service-a": " "}
    response = await post(context)
    assert response.status_code == 403
    assert not context[1].member_calls


@pytest.mark.parametrize("extra", ["organization_id", "line_subject"])
async def test_client_cannot_supply_ownership_or_line_identity(context, extra):
    response = await post(context, body={
        "service_id": "service-a", "member_number": "private-number", "name": "private-name", extra: "private-value",
    })
    assert response.status_code == 422
    assert response.json() == {"detail": {"error": "invalid_request"}}
    assert not context[1].member_calls


@pytest.mark.parametrize("error,code,kind", [
    (ExternalSystemUnavailableError("private provider response"), 503, "external_system_unavailable"),
    (ExternalBusinessNotConfiguredError("private config"), 503, "external_system_unavailable"),
    (TimeoutError("private timeout"), 503, "external_system_unavailable"),
    (RuntimeError("private exception"), 500, "internal_error"),
])
async def test_failure_is_not_business_mismatch_and_is_sanitized(context, caplog, error, code, kind):
    context[1].error = error
    response = await post(context)
    assert response.status_code == code
    assert response.json() == {"detail": {"error": kind}}
    assert "private" not in caplog.text
    assert "000123" not in caplog.text
    assert "test-incoming" not in caplog.text


async def test_summary_is_minimal_and_uses_configured_scope(context):
    response = await post(context, "members:summary", {"service_id": "service-b", "external_member_id": "stable-member"})
    assert response.status_code == 200
    assert response.json() == {"external_member_id": "stable-member", "display_label": "Display"}
    assert context[1].member_calls == [("organization-b", "stable-member")]


async def test_summary_not_found_is_distinct(context):
    context[1].error = ExternalMemberNotFoundError("private-id")
    response = await post(context, "members:summary", {"service_id": "service-a", "external_member_id": "missing"})
    assert response.status_code == 404
    assert response.json() == {"detail": {"error": "resource_not_found"}}


async def test_summary_wrong_member_is_dependency_failure(context):
    async def wrong_member(**kwargs):
        return ExternalMemberSummary("another-member", "private-label")
    context[1].get_member_summary = wrong_member
    response = await post(context, "members:summary", {"service_id": "service-a", "external_member_id": "wanted"})
    assert response.status_code == 503
    assert "private-label" not in response.text


async def test_jobs_reuse_existing_domain_and_gateway(context):
    fixture = Path(__file__).parents[1] / "app/testing/fixtures/external_business/normal.json"
    scenario = load_external_business_scenario(fixture)
    apply_to_fake(context[1], scenario)
    response = await post(context, "members:recommended-jobs", {"service_id": "service-a", "external_member_id": "stable-member"})
    assert response.status_code == 200
    assert response.json()[0]["external_job_id"] == scenario.recommended_jobs[0].external_job_id
    assert context[1].calls[-1].kwargs == {"external_organization_id": "organization-a", "external_member_id": "stable-member"}
    response = await post(context, "jobs:detail", {"service_id": "service-b", "external_job_id": scenario.job_detail.external_job_id})
    assert response.status_code == 200
    assert response.json()["version"] == scenario.job_detail.version
    assert context[1].calls[-1].kwargs["external_organization_id"] == "organization-b"


async def test_unwired_provider_fails_closed(context):
    context[0].state.admin_internal_business_gateway = None
    response = await post(context)
    assert response.status_code == 503


async def test_malformed_json_does_not_echo_input(context):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=context[0]), base_url="http://admin") as client:
        response = await client.post(
            "/internal/v1/members:verify",
            headers={"Authorization": "Bearer test-incoming", "Content-Type": "application/json"},
            content='{"name":"private-name", broken',
        )
    assert response.status_code == 422
    assert response.json() == {"detail": {"error": "invalid_request"}}


async def test_summary_does_not_serialize_additional_provider_identity(context):
    from dataclasses import dataclass

    @dataclass(frozen=True, slots=True)
    class BroadSummary(ExternalMemberSummary):
        line_subject: str = "private-line-identity"

    async def broad_summary(**kwargs):
        return BroadSummary(kwargs["external_member_id"], "Display")

    context[1].get_member_summary = broad_summary
    response = await post(context, "members:summary", {"service_id": "service-a", "external_member_id": "stable-member"})
    assert response.status_code == 200
    assert response.json() == {"external_member_id": "stable-member", "display_label": "Display"}


async def test_invalid_job_response_is_sanitized_dependency_error(context):
    async def invalid_jobs(**kwargs):
        return [{"provider_private_field": "private-response"}]

    context[1].list_recommended_jobs = invalid_jobs
    response = await post(context, "members:recommended-jobs", {"service_id": "service-a", "external_member_id": "stable-member"})
    assert response.status_code == 503
    assert response.json() == {"detail": {"error": "external_system_unavailable"}}


def test_openapi_matches_runtime_and_contains_no_line_identity(context):
    assert OUTPUT.read_text(encoding="utf-8") == serialize()
    artifact = json.loads(serialize())
    runtime = context[0].openapi()
    assert artifact["paths"] == runtime["paths"]
    assert artifact["components"] == runtime["components"]
    assert "line_subject" not in serialize()
    assert artifact["info"]["version"] == "1.0.0"
    assert artifact["x-contract-owner"] == "admin"
    for path in artifact["paths"].values():
        assert path["post"]["security"] == [{"LineToAdminBearer": []}]
        assert set(path["post"]["responses"]) == {"200", "401", "403", "404", "422", "500", "503"}
    schemas = artifact["components"]["schemas"]
    assert "external_member_id" not in schemas["NoMemberMatch"]["properties"]
    assert "external_member_id" not in schemas["MultipleMemberMatch"]["properties"]
    assert "external_member_id" in schemas["UniqueMemberMatch"]["required"]
    assert artifact["paths"]["/internal/v1/jobs:detail"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/ExternalJobDetail")


async def test_admin_entrypoint_wiring_without_reading_dotenv(monkeypatch):
    # Prevent existing module-level Settings() from opening any actual .env.
    from pydantic_settings import DotEnvSettingsSource
    monkeypatch.setattr(DotEnvSettingsSource, "_read_env_files", lambda self: {})
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/unused")
    monkeypatch.setenv("APP_ENV", "test")
    from app.core.settings_admin import AdminSettings
    from app.main_admin import create_admin_app

    settings = AdminSettings(
        _env_file=None, app_env="test", database_url="postgresql://unused/unused",
        admin_internal_api_bearer_token=SecretStr("test-incoming"),
        admin_internal_api_scopes={"service-a": "organization-a"},
        admin_local_integration_mode=False,
    )
    provider = Provider()
    app = create_admin_app(settings, external_business_gateway=provider)
    response = await post((app, provider))
    assert response.status_code == 200
    assert not any(path.startswith("/internal/") for path in app.openapi()["paths"])

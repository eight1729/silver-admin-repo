from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from pydantic_settings import DotEnvSettingsSource

from app.core.settings_admin import AdminSettings
from app.core.environment import application_environment
from app.adapter.line_internal_api import HttpLineInternalApiClient
from app.contracts.admin_line_internal_v1 import SendCapabilityRequest, ServiceOrganizationScope
from app.runtime.admin_line import build_production_admin_application
from app.adapter.local_inline_notification_queue import LocalInlineNotificationQueue


@pytest.mark.parametrize("value", ["staging", "development", "demo", "test", "unknown", "", None])
def test_reject_environment_before_reading_any_dotenv(monkeypatch, value):
    monkeypatch.delenv("APP_ENV", raising=False)
    def forbidden(*args, **kwargs):
        pytest.fail("unsupported environment attempted dotenv IO")
    monkeypatch.setattr(DotEnvSettingsSource, "_read_env_files", forbidden)
    with pytest.raises(ValueError, match="APP_ENV"):
        AdminSettings(app_env=value, database_url="postgresql://unused/unused")


def test_local_owner_dotenv_and_process_priority(tmp_path, monkeypatch):
    from app.core import settings_admin
    dotenv = tmp_path / "owner-fixture"
    dotenv.write_text('APP_ENV=production\nDATABASE_URL=postgresql://file/fixture\nADMIN_OIDC_AUDIENCE=file-audience\n', encoding="utf-8")
    monkeypatch.setattr(settings_admin, "ADMIN_ENV_FILE", dotenv)
    monkeypatch.setenv("APP_ENV", " LOCAL ")
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.setenv("ADMIN_OIDC_AUDIENCE", "process-audience")
    settings = AdminSettings()
    assert settings.app_env == "local"  # file cannot change source selection
    assert settings.database_url == "postgresql://file/fixture"
    assert settings.admin_oidc_audience == "process-audience"
    monkeypatch.setenv("ADMIN_OIDC_AUDIENCE", "")
    assert AdminSettings().admin_oidc_audience == ""


def test_production_never_reads_even_explicit_dotenv(tmp_path, monkeypatch):
    from app.core import settings_admin
    dotenv = tmp_path / "owner-fixture"
    dotenv.write_text('DATABASE_URL=postgresql://local/fixture\n', encoding="utf-8")
    monkeypatch.setattr(settings_admin, "ADMIN_ENV_FILE", dotenv)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL")
    original = DotEnvSettingsSource._read_env_files
    def checked(source):
        assert source.env_file is None  # no stat/read of a local source
        return original(source)
    monkeypatch.setattr(DotEnvSettingsSource, "_read_env_files", checked)
    with pytest.raises(ValidationError):
        AdminSettings(_env_file=dotenv)
    monkeypatch.setenv("DATABASE_URL", "postgresql://process/fixture")
    assert AdminSettings(_env_file=dotenv).database_url == "postgresql://process/fixture"


def complete_settings(**overrides):
    values = dict(app_env="production", database_url="postgresql://unused/unused",
        admin_oidc_enabled=True, admin_oidc_issuer="https://identity.invalid",
        admin_oidc_audience="offline-client", admin_oidc_jwks_url="https://identity.invalid/jwks",
        admin_internal_api_bearer_token=SecretStr("incoming-offline"),
        admin_internal_api_scopes={"svc":"org"}, current_db_business_centers={"org":"center"},
        admin_notification_runner_service_ids="svc",
        admin_line_internal_api_base_url="https://line.invalid",
        admin_line_internal_api_bearer_token=SecretStr("outgoing-offline"))
    values.update(overrides)
    return AdminSettings(_env_file=None, **values)


@pytest.mark.parametrize("changes", [
    {"database_url":""}, {"admin_oidc_enabled":False}, {"admin_oidc_audience":None},
    {"admin_oidc_issuer":None}, {"admin_oidc_jwks_url":None}, {"admin_oidc_algorithms":""},
    {"admin_notification_runner_service_ids":""}, {"admin_internal_api_scopes":{}},
    {"admin_internal_api_bearer_token":None}, {"current_db_business_centers":{}},
    {"admin_line_internal_api_base_url":None}, {"admin_line_internal_api_bearer_token":None},
    {"admin_line_internal_api_base_url":"http://line.invalid"},
    {"admin_oidc_jwks_url":"http://identity.invalid/jwks"},
])
def test_production_incomplete_startup_fails_offline(changes):
    with pytest.raises(Exception):
        complete_settings(**changes).validate_runtime()


@pytest.mark.parametrize("environment,limit", [("local", 10), ("production", None)])
def test_both_runtime_compositions_use_real_boundary_and_local_limit(environment, limit):
    settings = complete_settings(app_env=environment, admin_line_internal_api_base_url="https://silver-backend.ngrok.app")
    settings.validate_runtime()
    application, boundary, _ = build_production_admin_application(
        runtime_settings=settings, engine=object(), client=object(),
        external_business_gateway=object(), queue_gateway=LocalInlineNotificationQueue(),
        service_id="svc", organization_id="org", runner_service_ids=("svc",))
    assert isinstance(boundary.client, HttpLineInternalApiClient)
    assert application.notification_service._selected_recipient_limit == limit


@pytest.mark.asyncio
async def test_local_ngrok_uses_dedicated_service_bearer_without_logging(caplog):
    def handle(request):
        assert str(request.url) == "https://silver-backend.ngrok.app/internal/v1/send-capability:check"
        assert request.headers["Authorization"] == "Bearer outgoing-offline"
        return httpx.Response(200, json={"mode":"staging_live", "ready":True,
            "live_send_enabled":True, "max_recipients":10, "blocking_reasons":[]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = HttpLineInternalApiClient(client=http, base_url="https://silver-backend.ngrok.app",
            bearer_token=SecretStr("outgoing-offline"), environment="local")
        await client.check_send_capability(SendCapabilityRequest(scope=ServiceOrganizationScope(service_id="svc", organization_id="org")))
    assert "outgoing-offline" not in caplog.text


def test_public_openapi_contract_remains_unchanged():
    import json
    from scripts.export_application_openapi import schema
    artifact = Path(__file__).parents[1] / "contracts/admin-api-v1.openapi.json"
    assert schema() == json.loads(artifact.read_text(encoding="utf-8"))


@pytest.mark.asyncio
@pytest.mark.parametrize("line_limit,expected", [(None, 10), (20, 10), (3, 3)])
async def test_local_ui_effective_limit_keeps_line_wire_mode(line_limit, expected):
    from types import SimpleNamespace
    from app.api.admin_entry_deps import get_admin_line_send_mode_for_runtime
    from test_admin_send_capability import Client, composition, capability
    result = await get_admin_line_send_mode_for_runtime(
        SimpleNamespace(app_env="local"), integration=composition(Client(capability("staging_live", True, line_limit))), service_id="svc")
    assert result["max_recipients"] == expected
    assert result["mode"] == "staging_live"
    assert result["ready"] is True

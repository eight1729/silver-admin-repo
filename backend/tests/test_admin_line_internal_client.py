import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.adapter.line_internal_api import (
    HttpLineInternalApiClient,
    LineInternalApiConfigurationError,
    LineInternalApiPermanentError,
    LineInternalApiRetryableError,
)
from app.contracts.admin_line_internal_v1 import (
    BusinessNotificationMessage,
    LiffDeepLinkRequest,
    LinkageStatusBatchRequest,
    NotificationCommand,
    ServiceOrganizationScope,
    StagingSendReadinessRequest,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _command():
    return NotificationCommand(
        command_id=uuid4(), operation_id=uuid4(), target_id=uuid4(),
        scope=ServiceOrganizationScope(organization_id="org", service_id="svc"),
        external_member_id="member", job_id="job", job_version="v1",
        business_message=BusinessNotificationMessage(
            greeting="hello", introduction="intro", note="note"
        ),
        message_version="1", message_hash="a" * 64,
        idempotency_key="idem", correlation_id="corr", requested_at=NOW,
    )


def _result(command, status="accepted"):
    return {
        "command_id": str(command.command_id), "delivery_id": None,
        "operation_id": str(command.operation_id), "target_id": str(command.target_id),
        "external_member_id": command.external_member_id, "status": status,
        "reason_code": None, "accepted_at": NOW.isoformat(), "updated_at": NOW.isoformat(),
    }


@pytest.mark.asyncio
async def test_client_uses_bearer_and_exact_five_contract_operations():
    command = _command()
    calls = []
    def handler(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer admin-secret"
        if request.url.path.endswith("line-linkages:batch-get"):
            return httpx.Response(200, json={"items": [{"external_member_id": "member", "line_linked": True}]})
        if request.url.path.endswith("liff-deep-links:resolve"):
            return httpx.Response(200, json={"canonical_deep_link": "https://liff.line.me/x/liff/jobs/job?service_id=svc"})
        if request.url.path.endswith("staging-send-readiness:check"):
            return httpx.Response(200, json={"ready": True, "live_send_enabled": True, "max_recipients": 1, "message_prefix": "safe", "blocking_reasons": []})
        return httpx.Response(202 if request.method == "POST" else 200, json=_result(command))
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HttpLineInternalApiClient(
        client=http, base_url="https://line.internal", bearer_token=SecretStr("admin-secret"), environment="production"
    )
    assert (await client.submit_notification_command(command)).status.value == "accepted"
    assert (await client.get_notification_result(command.command_id)).command_id == command.command_id
    linkage = await client.batch_get_linkages(LinkageStatusBatchRequest(scope=command.scope, external_member_ids=("member",)))
    assert linkage.items[0].line_linked is True
    link = await client.resolve_deep_link(LiffDeepLinkRequest(scope=command.scope, job_id="job"))
    assert str(link.canonical_deep_link).startswith("https://liff.line.me/")
    readiness = await client.check_staging_send_readiness(StagingSendReadinessRequest(scope=command.scope))
    assert readiness.ready is True and readiness.max_recipients == 1
    assert [(r.method, r.url.path) for r in calls] == [
        ("POST", "/internal/v1/notification-commands"),
        ("GET", f"/internal/v1/notification-commands/{command.command_id}"),
        ("POST", "/internal/v1/line-linkages:batch-get"),
        ("POST", "/internal/v1/liff-deep-links:resolve"),
        ("POST", "/internal/v1/staging-send-readiness:check"),
    ]
    assert "line_subject" not in calls[0].content.decode()
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [httpx.ConnectError("x"), httpx.ReadTimeout("x")])
async def test_client_transport_failure_is_retryable_and_secret_safe(error):
    def handler(request): raise error
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HttpLineInternalApiClient(
        client=http, base_url="https://line.internal", bearer_token=SecretStr("never-leak"), environment="production"
    )
    with pytest.raises(LineInternalApiRetryableError) as caught:
        await client.submit_notification_command(_command())
    assert "never-leak" not in str(caught.value) and "never-leak" not in repr(client)
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,error_type", [(409, LineInternalApiPermanentError), (422, LineInternalApiPermanentError), (503, LineInternalApiRetryableError)]
)
async def test_client_classifies_http_failures_without_raw_body(status, error_type):
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(status, text="raw-private-response")))
    client = HttpLineInternalApiClient(
        client=http, base_url="https://line.internal", bearer_token=SecretStr("secret"), environment="production"
    )
    with pytest.raises(error_type) as caught:
        await client.submit_notification_command(_command())
    assert "raw-private-response" not in str(caught.value)
    await http.aclose()


@pytest.mark.asyncio
async def test_client_rejects_malformed_contract_response():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(202, json={"line_subject": "private"})))
    client = HttpLineInternalApiClient(
        client=http, base_url="https://line.internal", bearer_token=SecretStr("secret"), environment="production"
    )
    with pytest.raises(LineInternalApiRetryableError):
        await client.submit_notification_command(_command())
    await http.aclose()


@pytest.mark.parametrize(
    "base,token", [(None, SecretStr("x")), ("http://line.internal", SecretStr("x")), ("https://line.internal", None)]
)
def test_production_client_configuration_fails_closed(base, token):
    with pytest.raises(LineInternalApiConfigurationError):
        HttpLineInternalApiClient(
            client=httpx.AsyncClient(), base_url=base, bearer_token=token, environment="production"
        )

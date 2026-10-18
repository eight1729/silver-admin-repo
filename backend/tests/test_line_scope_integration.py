"""Admin HTTP requests against the actual sibling LINE ASGI routes, offline."""
import json
from pathlib import Path
import subprocess
import sys

import httpx
import pytest
from pydantic import SecretStr

from app.adapter.line_internal_api import HttpLineInternalApiClient, LineInternalApiScopeForbiddenError
from app.contracts.admin_line_internal_v1 import (
    CONTRACT_VERSION, ServiceOrganizationScope, LinkageStatusBatchRequest,
    LiffDeepLinkRequest, SendCapabilityRequest, StagingSendReadinessRequest,
)
from test_admin_line_internal_client import _command


async def test_real_admin_requests_and_line_scope_acceptance():
    backend = Path(__file__).resolve().parents[3] / "silver-line-repo" / "backend"
    if not backend.is_dir():
        pytest.skip("sibling LINE repository required for offline integration verification")
    artifact = Path(__file__).parents[1] / "contracts/line-internal-api-v1.openapi.json"
    assert artifact.read_bytes() == (backend / "contracts/line-internal-api-v1.openapi.json").read_bytes()
    assert json.loads(artifact.read_text())["info"]["version"] == CONTRACT_VERSION
    scopes = {"sandbox": "sandbox", "sumida": "sumida_shrc"}
    peer = subprocess.Popen([sys.executable, str(Path(__file__).with_name("line_scope_peer.py")), str(backend)],
        cwd=backend, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
    calls = []
    def transport(request):
        calls.append((request.method, request.url.path))
        peer.stdin.write(json.dumps({"scopes": scopes, "method": request.method,
            "path": request.url.path, "headers": dict(request.headers),
            "body": request.content.decode()}) + "\n")
        peer.stdin.flush()
        reply = peer.stdout.readline()
        assert reply, "offline LINE peer exited unexpectedly"
        response = json.loads(reply)
        return httpx.Response(response["status"], json=response["body"])
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            client = HttpLineInternalApiClient(client=http, base_url="https://offline.test",
                bearer_token=SecretStr("offline-internal"), environment="production")
            for service, org in tuple(scopes.items()):
                scope = ServiceOrganizationScope(service_id=service, organization_id=org)
                calls_for_scope = [
                    lambda: client.batch_get_linkages(LinkageStatusBatchRequest(scope=scope, external_member_ids=("fictional-member",))),
                    lambda: client.resolve_deep_link(LiffDeepLinkRequest(scope=scope, job_id="fictional-job")),
                    lambda: client.check_send_capability(SendCapabilityRequest(scope=scope)),
                    lambda: client.check_staging_send_readiness(StagingSendReadinessRequest(scope=scope)),
                ]
                replies = [await call() for call in calls_for_scope]
                assert replies[0].items[0].line_linked is False
                assert f"service_id={service}" in str(replies[1].canonical_deep_link)
                command = _command().model_copy(update={"scope": scope, "idempotency_key": service})
                assert (await client.submit_notification_command(command)).status.value == "accepted"
                assert (await client.get_notification_result(command.command_id)).status.value == "recipient_not_linked"
                assert (await client.submit_notification_command(command)).status.value == "recipient_not_linked"
                # Saved results/replays cannot bypass current permission; all
                # other real Admin requests also fail with the same safe error.
                scopes = {key: value for key, value in scopes.items() if key != service}
                for call in calls_for_scope + [lambda: client.get_notification_result(command.command_id),
                                               lambda: client.submit_notification_command(command)]:
                    with pytest.raises(LineInternalApiScopeForbiddenError):
                        await call()
                scopes = {"sandbox": "sandbox", "sumida": "sumida_shrc"}
            for service, org in [("sumida", "sandbox"), ("sandbox", "sumida_shrc"), ("silver-sumida", "sandbox")]:
                with pytest.raises(LineInternalApiScopeForbiddenError):
                    await client.batch_get_linkages(LinkageStatusBatchRequest(
                        scope=ServiceOrganizationScope(service_id=service, organization_id=org),
                        external_member_ids=("fictional-member",)))
            assert len(calls) == 29
    finally:
        peer.stdin.close()
        try:
            peer.wait(timeout=10)
        finally:
            if peer.poll() is None:
                peer.kill()
            peer.stdout.close()
    assert peer.returncode == 0

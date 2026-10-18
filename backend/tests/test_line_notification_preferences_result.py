"""Provider-generated refusal results cross the real HTTP consumer/reconciler."""
import importlib.util
from pathlib import Path
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.adapter.line_internal_api import HttpLineInternalApiClient
from app.application.admin_line_dispatch import AdminLineOutboxDispatcher, AdminLineResultReconciler
from app.domain.enums.enums import DeliveryStatus
from app.domain.models.admin_notification import NotificationOutboxState
from test_admin_line_dispatch import Repo, _outbox, NOW


@pytest.mark.parametrize("reason", ["notification_opted_out", "notification_preferences_unanswered"])
async def test_line_provider_refusal_is_durable_terminal_admin_result(reason):
    provider_path = Path(__file__).resolve().parents[3] / "silver-line-repo/backend/app/schemas/line_internal_contract.py"
    if not provider_path.is_file():
        pytest.skip("Cross-repository verification requires the LINE checkout alongside Admin")
    spec = importlib.util.spec_from_file_location("line_provider_preferences_contract", provider_path)
    provider = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(provider)
    item = replace(_outbox(), state=NotificationOutboxState.ACCEPTED)
    repo = Repo(item)
    result = provider.NotificationResult(
        command_id=item.command_id, operation_id=item.operation_id, target_id=item.target_id,
        delivery_id=uuid4(), external_member_id=item.external_member_id,
        status="failed", reason_code=reason, accepted_at=NOW, updated_at=NOW, sent_at=None,
    )
    calls = []
    def response(request):
        calls.append(request.method)
        assert request.method == "GET"  # A refusal must not trigger another submit.
        assert request.url.path == f"/internal/v1/notification-commands/{item.command_id}"
        assert request.headers["Authorization"] == "Bearer fictional-token"
        return httpx.Response(200, json=result.model_dump(mode="json"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
        client = HttpLineInternalApiClient(client=http, base_url="https://line.invalid",
                                          bearer_token=SecretStr("fictional-token"), environment="production")
        reconciler = AdminLineResultReconciler(repository=repo, line_client=client)
        await reconciler.reconcile_operation(service_id=item.service_id, operation_id=item.operation_id)
        assert repo.delivery.status is DeliveryStatus.FAILED
        assert repo.delivery.error_code == reason and repo.delivery.sent_at is None
        assert repo.item.state is NotificationOutboxState.RECONCILED
        await reconciler.reconcile_operation(service_id=item.service_id, operation_id=item.operation_id)
        await AdminLineOutboxDispatcher(repository=repo, line_client=client).dispatch_operation(
            service_id=item.service_id, operation_id=item.operation_id)
        assert calls == ["GET"]

"""Scope rejection converges without inventing a delivery result or reposting."""
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.adapter.line_internal_api import LineInternalApiScopeForbiddenError
from app.application.admin_line_dispatch import AdminLineOutboxDispatcher, AdminLineResultReconciler
from app.application.admin_notification_runner import AdminNotificationRunner
from app.application.admin_service import AdminApplicationService
from app.api.routes.admin import router
from app.api.admin_auth import require_admin_viewer
from app.api.admin_entry_deps import get_admin_application_service
from app.domain.enums.enums import DeliveryStatus, OperationStatus
from app.domain.models.admin_notification import NotificationOutboxState
from test_admin_state_recovery import db, seed, dispatch
from test_result_404_convergence import client
from test_admin_line_boundary import External

DENIED = {"detail": {"error": "scope_forbidden"}}


@pytest.mark.parametrize("already_accepted", [False, True])
async def test_scope_denial_stops_runner_and_preserves_saved_scope(db, already_accepted):
    repo, now, op, items = await seed(db)
    if already_accepted:
        await dispatch(repo, op, [None])
    calls = []
    def reject(request):
        calls.append(request)
        return httpx.Response(403, json=DENIED)
    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as http:
        line = client(http)
        runner = AdminNotificationRunner(repository=repo, service_ids=["svc"],
            dispatcher=AdminLineOutboxDispatcher(repository=repo, line_client=line),
            reconciler=AdminLineResultReconciler(repository=repo, line_client=line))
        for _ in range(3):
            await runner.run_cycle()
    assert len(calls) == 1
    assert calls[0].method == ("GET" if already_accepted else "POST")
    delivery, = await repo.get_deliveries("svc", op.operation_id)
    outbox, = await repo.get_outbox_records("svc", op.operation_id)
    assert delivery.status is (DeliveryStatus.UNKNOWN if already_accepted else DeliveryStatus.FAILED)
    assert delivery.error_code == ("line_result_scope_forbidden" if already_accepted else "line_submission_permanent_failure")
    assert delivery.sent_at is None and delivery.error_message is None
    assert outbox.state is (NotificationOutboxState.RECONCILED if already_accepted else NotificationOutboxState.PERMANENT_FAILURE)
    assert (outbox.organization_id, outbox.service_id, outbox.command_id, outbox.idempotency_key) == (
        items[0].organization_id, items[0].service_id, items[0].command_id, items[0].idempotency_key)
    assert (await repo.get_operation("svc", op.operation_id)).status is OperationStatus.COMPLETED_WITH_ERRORS
    assert await repo.list_recovery_operations("svc") == ()


async def test_scope_denial_cannot_overwrite_concurrent_sent_result(db):
    repo, now, op, items = await seed(db)
    await dispatch(repo, op, [None])
    original, = await repo.get_deliveries("svc", op.operation_id)
    sent = replace(original, status=DeliveryStatus.SENT, sent_at=now[0])
    class Results:
        async def get_notification_result(self, command_id):
            await repo.reconcile_outbox_result("svc", op.operation_id, items[0].outbox_id, sent)
            raise LineInternalApiScopeForbiddenError()
    await AdminLineResultReconciler(repository=repo, line_client=Results()).reconcile_operation(
        service_id="svc", operation_id=op.operation_id)
    assert await repo.get_deliveries("svc", op.operation_id) == (sent,)


async def test_deep_link_scope_denial_is_safe_dependency_error():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403, json=DENIED))) as peer:
        service = AdminApplicationService(notification_service=SimpleNamespace(),
            external_business_gateway=External(), demo_service_id="svc",
            line_linked_member_ids=frozenset(), expose_line_subjects=False,
            line_internal_client=client(peer), organization_id_resolver=lambda _: "org")
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_admin_viewer] = lambda: SimpleNamespace(service_id="svc")
        app.dependency_overrides[get_admin_application_service] = lambda: service
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://offline.test") as http:
            response = await http.get("/admin/jobs/job/notification-link")
    assert response.status_code == 503
    assert response.json() == {"detail": {"error": "service_unavailable"}}

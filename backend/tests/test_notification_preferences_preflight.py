"""Saved targets are rechecked through the real Admin batch consumer for both workflows."""
from types import SimpleNamespace
import pytest

from app.application.automatic_selection import confirmation_identity
from app.application.notification_service import OperationNotSendableError
from app.domain.enums.notification_type import NotificationType
from test_automatic_notification import world, db, prepare, send


async def setup(db, automatic, statuses):
    w = await world(db, len(statuses))
    if automatic:
        op = await prepare(w)
    else:
        item = await w.app.create_operation(service_id="svc", staff_id="staff", job_id="JOB-001",
            notification_type=NotificationType.NEW_JOB_MATCH, greeting="hello", introduction="job", note="note")
        op = item.operation_id
        await w.app.replace_targets(service_id="svc", operation_id=op, staff_id="staff", selected_member_ids=tuple(w.members))
    calls = []
    async def batch(request):
        calls.append(request)
        return {"items": [{"external_member_id": m, "line_linked": statuses[m] != "not_linked",
            "job_notification_status": "unknown" if statuses[m] == "not_linked" else statuses[m]} for m in request.external_member_ids]}
    w.app._line_internal_client = SimpleNamespace(batch_get_linkages=batch)
    return w, op, calls


async def validate(w, op):
    summary = await w.app.validate(service_id="svc", operation_id=op, staff_id="staff", request_id="validate")
    current = await w.app.get_operation("svc", op)
    return summary, confirmation_identity(current.operation, current.targets)


@pytest.mark.parametrize("automatic", [False, True])
async def test_mixed_latest_preferences_and_explicit_confirmation(db, automatic):
    statuses = dict(zip([f"m-{i}" for i in range(4)], ["enabled", "opted_out", "unanswered", "not_linked"]))
    w, op, calls = await setup(db, automatic, statuses)
    summary, token = await validate(w, op)
    assert summary.eligible_count == 1 and summary.selected_target_count == 4
    assert {item.member_id: item.reason for item in summary.target_results} == {
        "m-0": None, "m-1": "notification_opted_out", "m-2": "notification_preferences_unanswered", "m-3": "line_not_linked"}
    with pytest.raises(OperationNotSendableError):
        await send(w, op, None)
    assert not w.dispatched
    await send(w, op, token)
    deliveries = await w.repo.get_deliveries("svc", op)
    assert {d.member_id for d in deliveries if d.status.value == "pending"} == {"m-0"}
    assert len(w.dispatched) == 1
    assert len(calls) == 2  # One batch per validation, including immediately before send.


@pytest.mark.parametrize("automatic", [False, True])
async def test_public_validation_token_is_consumed_by_send_with_same_recipient_set(db, automatic):
    import httpx
    from fastapi import FastAPI
    from app.api.routes.admin import router
    from app.api.admin_auth import require_admin_operator
    from app.api.admin_entry_deps import get_admin_application_service
    w, op, _ = await setup(db, automatic, {"m-0": "enabled", "m-1": "opted_out"})
    api = FastAPI()
    api.include_router(router)
    api.dependency_overrides[get_admin_application_service] = lambda: w.app
    api.dependency_overrides[require_admin_operator] = lambda: SimpleNamespace(service_id="svc", staff_id="staff")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="https://offline.test") as client:
        response = await client.post(f"/admin/notification-operations/{op}/validate")
        assert response.status_code == 200
        body = response.json()
        assert body["can_proceed"] and body["sendable_count"] == 1 and body["selected_count"] == 2
        assert body["target_results"][1]["reason"] == "notification_opted_out"
        assert len(body["confirmation_token"]) == 64
        assert (await client.post(f"/admin/notification-operations/{op}/send")).status_code == 409
        result = await client.post(f"/admin/notification-operations/{op}/send", json={"confirmation_token": body["confirmation_token"]})
        assert result.status_code == 200
    assert {o.external_member_id for o in await w.repo.get_outbox_records("svc", op)} == {"m-0"}


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("state", ["opted_out", "unanswered", "unknown", "not_linked"])
async def test_no_sendable_targets_and_unknown_are_closed(db, automatic, state):
    w, op, _ = await setup(db, automatic, {"m-0": state})
    summary, token = await validate(w, op)
    assert summary.eligible_count == 0 and not summary.can_proceed
    with pytest.raises(OperationNotSendableError): await send(w, op, token)
    assert not w.dispatched and not await w.repo.get_deliveries("svc", op)


@pytest.mark.parametrize("automatic", [False, True])
async def test_changed_preferences_invalidate_confirmed_set_and_revalidation_recovers(db, automatic):
    statuses = {"m-0": "enabled", "m-1": "enabled"}
    w, op, _ = await setup(db, automatic, statuses)
    _, token = await validate(w, op)
    statuses["m-1"] = "opted_out"
    with pytest.raises(OperationNotSendableError): await send(w, op, token)
    assert not w.dispatched and not await w.repo.get_deliveries("svc", op)
    summary, new_token = await validate(w, op)
    assert summary.eligible_count == 1 and new_token != token
    statuses["m-1"] = "enabled"
    with pytest.raises(OperationNotSendableError): await send(w, op, new_token)
    summary, token = await validate(w, op)
    assert summary.eligible_count == 2
    await send(w, op, token)
    assert len(w.dispatched) == 1


@pytest.mark.parametrize("automatic", [False, True])
async def test_missing_field_partial_response_and_dependency_failure_are_not_permission(db, automatic):
    w, op, _ = await setup(db, automatic, {"m-0": "enabled"})
    async def legacy(request): return {"items": [{"external_member_id": "m-0", "line_linked": True}]}
    async def incomplete(request): return {"items": []}
    from app.adapter.line_internal_api import LineInternalApiScopeForbiddenError
    async def forbidden(request): raise LineInternalApiScopeForbiddenError("forbidden")
    for batch in (legacy, incomplete, forbidden):
        w.app._line_internal_client = SimpleNamespace(batch_get_linkages=batch)
        summary, _ = await validate(w, op)
        assert not summary.can_proceed
        assert summary.target_results[0].reason == "notification_preferences_unavailable"
        assert summary.invalid_count == 1
    assert not w.dispatched


@pytest.mark.parametrize("automatic", [False, True])
async def test_opt_out_does_not_relax_incomplete_business_validation(db, automatic):
    from dataclasses import replace
    w, op, _ = await setup(db, automatic, {"m-0": "enabled", "m-1": "opted_out"})
    original = w.external.validate_notification_targets
    async def incomplete(**kwargs):
        result = await original(**kwargs)
        return replace(result, members=tuple(item for item in result.members if item.external_member_id != "m-1"))
    w.external.validate_notification_targets = incomplete
    summary, _ = await validate(w, op)
    assert not summary.can_proceed and summary.invalid_count == 1
    assert summary.target_results[1].reason == "member_not_found"


async def test_manual_confirmation_rejects_message_change_and_concurrent_send(db):
    import asyncio
    from app.domain.errors.admin_notification_repository import ReservedNotificationMutationError
    w, op, _ = await setup(db, False, {"m-0": "enabled"})
    _, token = await validate(w, op)
    await w.app.update_operation(service_id="svc", operation_id=op, staff_id="staff",
                                 greeting="changed", introduction="job", note="note")
    with pytest.raises(OperationNotSendableError): await send(w, op, token)
    _, token = await validate(w, op)
    entered, resume = asyncio.Event(), asyncio.Event()
    original = w.external.validate_notification_targets
    async def paused(**kwargs):
        entered.set()
        await resume.wait()
        return await original(**kwargs)
    w.external.validate_notification_targets = paused
    first = asyncio.create_task(send(w, op, token))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        with pytest.raises((OperationNotSendableError, ReservedNotificationMutationError)):
            await send(w, op, token)
    finally:
        resume.set()
    await first
    assert len(w.dispatched) == 1 and len(await w.repo.get_outbox_records("svc", op)) == 1

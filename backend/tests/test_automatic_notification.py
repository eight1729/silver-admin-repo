"""Automatic selection/confirmation using disposable SQL and canonical LINE doubles only."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.application.automatic_selection import automatic_context, select_automatic_members, canonical
from app.application.admin_service import AdminCandidate, AdminDependencyUnavailableError
from app.application.notification_service import OperationNotSendableError, ValidateNotificationOperationCommand
from app.domain.errors.errors import ExternalSystemUnavailableError, ExternalMemberNotFoundError, ExternalJobNotFoundError
from app.domain.models.external_business import CandidateMember, ExternalMemberSummary
from app.domain.models.notification import MemberValidationResult, NotificationValidationResult
from app.domain.enums.enums import NotificationEligibilityReason, JobStatus
from app.domain.enums.notification_type import NotificationType
from app.domain.errors.admin_notification_repository import ReservedNotificationMutationError
from app.adapter.local_inline_notification_queue import LocalInlineNotificationQueue
from app.runtime.admin_line import build_production_admin_application
from app.testing.local_integration import _build_external_business_fake
from test_admin_state_recovery import db, NOW
from test_admin_environment import complete_settings
from test_admin_send_capability import Client, capability


@pytest.mark.parametrize("count", [0, 1, 50, 100, 101])
def test_selection_size_numeric_order_and_no_replacement(count):
    candidates = [AdminCandidate(f"id-{i}", "test", True, True, None,
                  member_number=str(i).zfill(5), recommendation_level=5) for i in range(count)]
    assert select_automatic_members(candidates) == tuple(f"id-{i}" for i in reversed(range(count)))[:100]


def test_selection_large_numbers_ties_unknown_level_unlinked_and_invalid_number():
    def c(identity, number, level=5, linked=True):
        return AdminCandidate(identity, "test", linked, True, None, member_number=number, recommendation_level=level)
    assert select_automatic_members([c("b", "0009"), c("a", "9"), c("big", "9" * 5000),
        c("null", "999", None), c("low", "999", 4), c("unlinked", "999", linked=False)]) == ("big", "a", "b")
    for number in [None, "", "abc", "１２３"]:
        with pytest.raises(ValueError): select_automatic_members([c("invalid", number)])


async def world(db, count=3, environment="production"):
    external = _build_external_business_fake()
    members = [f"m-{i}" for i in range(count)]
    external.candidate_members_result = [CandidateMember(m, "FICTIONAL DISPLAY", True, (), None,
        member_number=str(i+1), recommendation_level=5) for i, m in enumerate(members)]
    blocked = set()
    linked = {m: True for m in members}
    async def validation(**kwargs):
        return NotificationValidationResult("JOB-001", True, "v1", None, tuple(
            MemberValidationResult(m, m not in blocked, NotificationEligibilityReason.MEMBER_NO_LONGER_CANDIDATE if m in blocked else None)
            for m in kwargs["external_member_ids"]), NOW, None)
    external.validate_notification_targets = validation
    async def summary(**kwargs):
        m = kwargs["external_member_id"]
        if m not in members: raise ExternalMemberNotFoundError("missing")
        return ExternalMemberSummary(m, "FICTIONAL DISPLAY", str(members.index(m)+1), "4321" if m == members[0] else None)
    external.get_member_summary = summary
    application, boundary, _ = build_production_admin_application(runtime_settings=complete_settings(app_env=environment),
        engine=db, client=object(), external_business_gateway=external, queue_gateway=LocalInlineNotificationQueue(),
        service_id="svc", organization_id="org-fake-silver-001", runner_service_ids=("svc",))
    calls = []
    async def lookup(request):
        calls.append(tuple(request.external_member_ids))
        return {"items": [{"external_member_id": m, "line_linked": linked[m]} for m in request.external_member_ids]}
    application._line_internal_client = SimpleNamespace(batch_get_linkages=lookup)
    application.notification_service._reservation_guard.client = Client(capability())
    dispatched = []
    async def capture(**kwargs): dispatched.append(kwargs)
    application.notification_service._queue_gateway.register_handler(capture)
    return SimpleNamespace(app=application, repo=boundary.repository, external=external, linked=linked,
        members=members, blocked=blocked, calls=calls, dispatched=dispatched)


async def prepare(w):
    choice = await w.app.automatic_selection("svc", "JOB-001")
    op = await w.app.create_operation(service_id="svc", staff_id="staff", job_id="JOB-001",
        notification_type=NotificationType.NEW_JOB_MATCH, greeting="hello", introduction="job", note="note", automatic_selection=True)
    await w.app.replace_targets(service_id="svc", operation_id=op.operation_id, staff_id="staff",
                                selected_member_ids=choice["selected_member_ids"])
    return op.operation_id


async def validate(w, op):
    await w.app.validate(service_id="svc", operation_id=op, staff_id="staff", request_id="validation")
    return await w.app.confirmation("svc", op)


async def send(w, op, token):
    return await w.app.send(service_id="svc", operation_id=op, staff_id="staff", request_id="send", confirmation_token=token)


async def test_confirmation_s_v_e_exclusion_latch_and_explicit_reselection(db):
    w = await world(db)
    op = await prepare(w)
    w.blocked.add("m-0")
    view = await validate(w, op)
    assert (view["initial_count"], view["selected_count"], view["sendable_count"], view["excluded_count"]) == (3, 3, 2, 1)
    assert len(view["targets"]) == 3 and view["can_send"]
    assert view["targets"][0]["mobile_phone_last4"] == "4321"
    w.blocked.clear()
    view = await validate(w, op)
    assert view["sendable_count"] == 2  # E never silently revives.
    await w.app.update_operation(service_id="svc", operation_id=op, staff_id="staff", greeting="hello", introduction="edited", note="note")
    assert (await validate(w, op))["sendable_count"] == 2  # Message edit preserves latch.
    await w.app.replace_targets(service_id="svc", operation_id=op, staff_id="staff", selected_member_ids=tuple(w.members), reinclude_member_ids=("m-0",))
    assert (await validate(w, op))["sendable_count"] == 3


@pytest.mark.parametrize("change", ["link", "eligibility", "message", "targets", "revalidate", "missing_token"])
async def test_stale_confirmation_never_reserves_send(db, change):
    w = await world(db)
    op = await prepare(w)
    view = await validate(w, op)
    if change == "link": w.linked["m-0"] = False
    if change == "eligibility": w.blocked.add("m-0")
    if change == "message": await w.app.update_operation(service_id="svc", operation_id=op, staff_id="staff", greeting="hi", introduction="changed", note="note")
    if change == "targets": await w.app.replace_targets(service_id="svc", operation_id=op, staff_id="staff", selected_member_ids=("m-0",))
    if change == "revalidate": await validate(w, op)
    with pytest.raises(OperationNotSendableError): await send(w, op, None if change == "missing_token" else view["confirmation_token"])
    assert not await w.repo.get_outbox_records("svc", op)
    assert not w.dispatched


async def test_confirmed_send_reserves_only_v_and_duplicate_send_does_not_dispatch(db):
    w = await world(db)
    op = await prepare(w)
    w.linked["m-0"] = False
    view = await validate(w, op)
    w.linked["m-0"] = True
    await send(w, op, view["confirmation_token"])
    outbox = await w.repo.get_outbox_records("svc", op)
    assert {o.external_member_id for o in outbox} == {"m-1", "m-2"}
    await send(w, op, view["confirmation_token"])
    assert len(w.dispatched) == 1
    stored = await w.repo.get_operation("svc", op)
    audits = await w.repo.get_audit_events("svc", op)
    serialized = str(canonical(stored.validation_snapshot)) + str(outbox) + str(audits)
    assert "FICTIONAL DISPLAY" not in serialized and "4321" not in serialized


async def test_linkage_failure_incomplete_data_and_candidate_failure_are_not_unlinked(db):
    w = await world(db)
    async def incomplete(request): return {"items": []}
    w.app._line_internal_client.batch_get_linkages = incomplete
    with pytest.raises(AdminDependencyUnavailableError): await w.app.automatic_selection("svc", "JOB-001")
    w = await world(db)
    op = await prepare(w)
    view = await validate(w, op)
    w.app._line_internal_client.batch_get_linkages = incomplete
    with pytest.raises((OperationNotSendableError, AdminDependencyUnavailableError)):
        await send(w, op, view["confirmation_token"])
    assert not await w.repo.get_outbox_records("svc", op)
    w = await world(db)
    w.external.raise_on_next_list_candidate_members = ExternalSystemUnavailableError("offline")
    with pytest.raises(ExternalSystemUnavailableError): await w.app.automatic_selection("svc", "JOB-001")


async def test_zero_closed_job_and_wrong_initial_selection_rejected(db):
    w = await world(db, 0)
    assert not (await w.app.automatic_selection("svc", "JOB-001"))["selected_member_ids"]
    with pytest.raises(ValueError): await prepare(w)
    w = await world(db)
    w.external.job_detail_result = replace(w.external.job_detail_result, status=JobStatus.CLOSED)
    with pytest.raises(ValueError): await w.app.automatic_selection("svc", "JOB-001")


async def test_edit_over_100_preserves_existing_local_and_capability_limits(db):
    w = await world(db, 101)
    op = await prepare(w)
    assert len((await w.app.get_operation("svc", op)).targets) == 101
    await w.app.replace_targets(service_id="svc", operation_id=op, staff_id="staff", selected_member_ids=tuple(w.members))
    view = await validate(w, op)
    assert view["initial_count"] == 100 and view["sendable_count"] == 101
    w.app.notification_service._reservation_guard.client = Client(capability(limit=100))
    with pytest.raises(OperationNotSendableError): await send(w, op, view["confirmation_token"])
    assert not await w.repo.get_outbox_records("svc", op)
    w.app.notification_service._reservation_guard.client = Client(capability(limit=None))
    view = await validate(w, op)
    await send(w, op, view["confirmation_token"])
    assert len(await w.repo.get_outbox_records("svc", op)) == 101  # Disposable SQL only.
    w = await world(db, 11, environment="local")
    op = await prepare(w)
    view = await validate(w, op)
    assert view["selected_recipient_limit"] == 10 and not view["can_send"]
    with pytest.raises(OperationNotSendableError, match="local_recipient_limit"):
        await send(w, op, view["confirmation_token"])


async def test_concurrent_validation_fenced_and_reservation_rejects_edits(db):
    w = await world(db)
    op = await prepare(w)
    entered, resume = asyncio.Event(), asyncio.Event()
    original = w.external.validate_notification_targets
    async def paused(**kwargs):
        entered.set()
        await resume.wait()
        return await original(**kwargs)
    w.external.validate_notification_targets = paused
    running = asyncio.create_task(validate(w, op))
    await entered.wait()
    current = await w.repo.get_operation("svc", op)
    await w.repo.update_operation("svc", op, replace(current, message_hash="concurrent-change"))
    resume.set()
    with pytest.raises(ReservedNotificationMutationError): await running
    assert (await w.repo.get_operation("svc", op)).message_hash == "concurrent-change"
    assert not await w.repo.get_outbox_records("svc", op)


async def test_all_candidates_and_linkage_batches_are_used_before_top_100(db):
    w = await world(db, 501)
    selected = await w.app.automatic_selection("svc", "JOB-001")
    assert selected["selected_member_ids"] == tuple(f"m-{i}" for i in range(500, 400, -1))
    assert [len(call) for call in w.calls] == [500, 1]


async def test_missing_individual_verdict_stays_blocked_until_explicit_edit(db):
    w = await world(db)
    op = await prepare(w)
    original = w.external.validate_notification_targets
    async def missing(**kwargs):
        result = await original(**kwargs)
        return replace(result, members=result.members[1:])
    w.external.validate_notification_targets = missing
    view = await validate(w, op)
    assert not view["can_send"] and view["confirmation_token"] is None
    assert sorted(t["disposition"] for t in view["targets"]) == ["block", "send", "send"]
    w.external.validate_notification_targets = original
    assert not (await validate(w, op))["can_send"]


async def test_missing_job_cannot_silently_revive_excluded_selection(db):
    w = await world(db)
    op = await prepare(w)
    w.external.raise_on_next_get_job_detail = ExternalJobNotFoundError("missing")
    view = await validate(w, op)
    assert view["sendable_count"] == 0 and view["excluded_count"] == 3
    assert not (await validate(w, op))["can_send"]


async def test_scope_auth_and_selected_only_confirmation_api(db):
    import httpx
    from fastapi import FastAPI, HTTPException
    from app.api.routes.admin import router
    from app.api.admin_auth import require_admin_operator, require_admin_viewer
    from app.api.admin_entry_deps import get_admin_application_service
    w = await world(db, 101)
    op = await prepare(w)
    await validate(w, op)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_admin_application_service] = lambda: w.app
    staff = SimpleNamespace(service_id="svc", staff_id="staff")
    app.dependency_overrides[require_admin_operator] = lambda: staff
    app.dependency_overrides[require_admin_viewer] = lambda: staff
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline") as client:
        response = await client.get(f"/admin/notification-operations/{op}/confirmation")
        assert response.status_code == 200
        assert len(response.json()["targets"]) == 100
        assert "m-0" not in {t["member_id"] for t in response.json()["targets"]}
        result = await client.post(f"/admin/notification-operations/{op}/validate")
        assert result.status_code == 200 and len(result.json()["target_results"]) == 100
        assert result.json()["skipped_count"] == 1  # Legacy count includes the unselected candidate.
        assert (await client.post(f"/admin/notification-operations/{op}/send")).status_code == 409
        staff.service_id = "other"
        assert (await client.get(f"/admin/notification-operations/{op}/confirmation")).status_code == 404
        def viewer_only(): raise HTTPException(403)
        app.dependency_overrides[require_admin_operator] = viewer_only
        assert (await client.get(f"/admin/notification-operations/{op}/confirmation")).status_code == 403
    assert not await w.repo.get_outbox_records("svc", op)


@pytest.mark.parametrize("token_kind", ["other_operation", "tampered"])
async def test_confirmation_token_cannot_be_transferred_or_modified(db, token_kind):
    w = await world(db)
    first, second = await prepare(w), await prepare(w)
    first_view = await validate(w, first)
    second_view = await validate(w, second)
    assert first_view["confirmation_token"] != second_view["confirmation_token"]
    token = first_view["confirmation_token"] if token_kind == "other_operation" else "0" * 64
    with pytest.raises(OperationNotSendableError):
        await send(w, second, token)
    assert not await w.repo.get_outbox_records("svc", second)
    assert not w.dispatched


async def test_same_count_target_identity_replacement_invalidates_confirmation(db):
    w = await world(db)
    op = await prepare(w)
    await w.app.replace_targets(service_id="svc", operation_id=op, staff_id="staff",
                                selected_member_ids=("m-0", "m-1"))
    before = await validate(w, op)
    await w.app.replace_targets(service_id="svc", operation_id=op, staff_id="staff",
                                selected_member_ids=("m-1", "m-2"))
    after = await validate(w, op)
    assert before["sendable_count"] == after["sendable_count"] == 2
    with pytest.raises(OperationNotSendableError):
        await send(w, op, before["confirmation_token"])
    assert not await w.repo.get_outbox_records("svc", op)
    await send(w, op, after["confirmation_token"])
    assert {item.external_member_id for item in await w.repo.get_outbox_records("svc", op)} == {"m-1", "m-2"}


async def test_parallel_automatic_send_reserves_once(db):
    w = await world(db)
    op = await prepare(w)
    view = await validate(w, op)
    entered, resume = asyncio.Event(), asyncio.Event()
    original = w.external.validate_notification_targets
    async def paused(**kwargs):
        entered.set()
        await resume.wait()
        return await original(**kwargs)
    w.external.validate_notification_targets = paused
    first = asyncio.create_task(send(w, op, view["confirmation_token"]))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        with pytest.raises((OperationNotSendableError, ReservedNotificationMutationError)):
            await send(w, op, view["confirmation_token"])
    finally:
        resume.set()
    await first
    assert len(w.dispatched) == 1
    assert {item.external_member_id for item in await w.repo.get_outbox_records("svc", op)} == set(w.members)

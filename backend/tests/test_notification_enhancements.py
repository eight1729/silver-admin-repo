from dataclasses import replace
from datetime import timezone
from types import SimpleNamespace
import pytest

from test_admin_state_recovery import db, dispatch
from test_automatic_notification import world, prepare, validate, send
from app.domain.enums.enums import DeliveryStatus, OperationStatus
from app.domain.enums.notification_type import NotificationType
from app.domain.errors.errors import ExternalSystemUnavailableError
from app.application.admin_service import AdminExternalSystemUnavailableError
from app.application.notification_service import OperationNotEditableError
from app.domain.models.notification_text import final_notification_text, validate_final_text, utf16_units, MessageTooLongError
from app.domain.models.delivery_population import selected_deliveries, projected_operation


@pytest.mark.parametrize("automatic", [False, True])
async def test_same_operation_recovers_external_block_and_preserves_business_exclusions(db, automatic):
    w = await world(db)
    op = await w.app.create_operation(service_id="svc", staff_id="staff", job_id="JOB-001",
        notification_type=NotificationType.NEW_JOB_MATCH, greeting="hello", introduction="job", note="note", automatic_selection=automatic)
    await w.app.replace_targets(service_id="svc", operation_id=op.operation_id, staff_id="staff", selected_member_ids=tuple(w.members))
    original = w.external.get_job_detail
    async def timeout(**kwargs): raise ExternalSystemUnavailableError("timeout")
    w.external.get_job_detail = timeout
    with pytest.raises(AdminExternalSystemUnavailableError):
        await w.app.validate(service_id="svc", operation_id=op.operation_id, staff_id="staff", request_id="fail")
    blocked = await w.repo.get_operation("svc", op.operation_id)
    assert blocked.status is OperationStatus.BLOCKED_EXTERNAL_SYSTEM
    if automatic:
        context = dict(blocked.validation_snapshot["automatic_selection"])
        context["excluded"] = {"m-0": {"reason": "external_timeout", "disposition": "block"},
            "m-1": {"reason": "member_ineligible", "disposition": "skip"}}
        await w.repo.update_operation("svc", op.operation_id, replace(blocked, validation_snapshot={"automatic_selection": context}))
    w.external.get_job_detail = original
    await w.app.update_operation(service_id="svc", operation_id=op.operation_id, staff_id="staff", greeting="edited", introduction="job", note="note")
    await w.app.replace_targets(service_id="svc", operation_id=op.operation_id, staff_id="staff", selected_member_ids=tuple(w.members))
    result = await w.app.validate(service_id="svc", operation_id=op.operation_id, staff_id="staff", request_id="retry")
    assert result.can_proceed
    assert result.selected_target_count == 3
    assert result.eligible_count == (2 if automatic else 3)
    if automatic:
        current = await w.repo.get_operation("svc", op.operation_id)
        assert set(current.validation_snapshot["automatic_selection"]["excluded"]) == {"m-1"}


@pytest.mark.parametrize("skip", [False, True])
async def test_three_candidates_two_selected_population_and_completion(db, skip):
    w = await world(db)
    op = await prepare(w)
    await w.app.replace_targets(service_id="svc", operation_id=op, staff_id="staff", selected_member_ids=("m-0", "m-1"))
    if skip: w.linked["m-1"] = False
    view = await validate(w, op)
    await send(w, op, view["confirmation_token"])
    rows = await w.repo.get_deliveries("svc", op)
    assert {r.member_id for r in rows} == {"m-0", "m-1"}
    assert len(await w.repo.get_targets("svc", op)) == 3
    stored = await w.repo.get_operation("svc", op)
    for _ in range(1 if skip else 2):
        await dispatch(w.repo, stored, [None])
    outbox = await w.repo.get_outbox_records("svc", op)
    for item in outbox:
        row = next(row for row in rows if row.member_id == item.external_member_id)
        await w.repo.reconcile_outbox_result("svc", op, item.outbox_id, replace(row, status=DeliveryStatus.SENT))
    result = await w.repo.refresh_delivery_aggregate("svc", op)
    assert result.status is (OperationStatus.COMPLETED_WITH_ERRORS if skip else OperationStatus.COMPLETED)
    if not skip:
        from uuid import uuid4
        # Historical not_selected row is retained physically but projected out of
        # both Operation and Delivery APIs. Stored audit/status remain historical.
        legacy = replace(rows[0], delivery_id=uuid4(), member_id="m-2", status=DeliveryStatus.SKIPPED, error_code="not_selected")
        await w.repo.add_deliveries("svc", op, (legacy,))
        await w.repo.update_operation("svc", op, replace(result, status=OperationStatus.COMPLETED_WITH_ERRORS))
        audit_before = await w.repo.get_audit_events("svc", op)
        assert (await w.app.get_operation("svc", op)).operation.status is OperationStatus.COMPLETED
        assert len(await w.app.list_deliveries("svc", op)) == 2
        assert len(await w.repo.get_deliveries("svc", op)) == 3
        assert (await w.repo.get_operation("svc", op)).status is OperationStatus.COMPLETED_WITH_ERRORS
        assert await w.repo.get_audit_events("svc", op) == audit_before
    with pytest.raises(OperationNotEditableError):
        await w.app.update_operation(service_id="svc", operation_id=op, staff_id="staff", greeting="no", introduction="no", note="no")


def test_historical_population_requires_consistent_frozen_evidence():
    op = SimpleNamespace(send_requested_at="reserved", status=OperationStatus.COMPLETED_WITH_ERRORS,
        validation_snapshot={"target_results": [{"member_id": "a", "selected": True}, {"member_id": "b", "selected": False}]})
    targets = [SimpleNamespace(member_id="a", selected=True), SimpleNamespace(member_id="b", selected=False)]
    rows = [SimpleNamespace(member_id="a", status=DeliveryStatus.SENT, error_code=None),
            SimpleNamespace(member_id="b", status=DeliveryStatus.SKIPPED, error_code="not_selected")]
    assert selected_deliveries(op, targets, rows) == (rows[0],)
    targets[1].selected = True
    assert selected_deliveries(op, targets, rows) == tuple(rows)
    targets.clear()
    assert selected_deliveries(op, targets, rows) == tuple(rows)


@pytest.mark.parametrize("size", [4999, 5000, 5001])
def test_final_text_boundary_includes_prefix_url_newlines_and_emoji(size):
    message = SimpleNamespace(greeting="[TEST]\n\n[TEST]\n\n😀", introduction="job", note="note")
    link = "https://liff.line.me/example/jobs/job"
    base = final_notification_text(message, link, "[TEST]")
    message.note += "a" * (size - utf16_units(base))
    final = final_notification_text(message, link, "[TEST]")
    assert utf16_units(final) == size and final.count("[TEST]") == 1
    if size > 5000:
        with pytest.raises(MessageTooLongError): validate_final_text(final)
    else: assert validate_final_text(final) == final


async def test_admin_message_guard_rejects_long_save_and_dependency_failure(db):
    w = await world(db); op = await prepare(w)
    with pytest.raises(MessageTooLongError):
        await w.app.update_operation(service_id="svc", operation_id=op, staff_id="staff", greeting="😀"*2500, introduction="job", note="note")
    assert (await w.repo.get_operation("svc", op)).message.greeting == "hello"
    async def unavailable(*args): raise ExternalSystemUnavailableError("unavailable")
    w.app.notification_service._message_guard = unavailable
    with pytest.raises(AdminExternalSystemUnavailableError):
        await w.app.validate(service_id="svc", operation_id=op, staff_id="staff", request_id="fail")
    assert not await w.repo.get_outbox_records("svc", op)


@pytest.mark.parametrize("automatic", [False, True])
async def test_unfilled_template_can_save_but_cannot_validate_or_send(db, automatic):
    w = await world(db)
    op = await w.app.create_operation(service_id="svc", staff_id="staff", job_id="JOB-001",
        notification_type=NotificationType.NEW_JOB_MATCH, greeting="本文\n　【未入力：配分金】",
        introduction="\u2063", note="\u2063", automatic_selection=automatic)
    await w.app.replace_targets(service_id="svc", operation_id=op.operation_id, staff_id="staff", selected_member_ids=tuple(w.members))
    result = await w.app.validate(service_id="svc", operation_id=op.operation_id, staff_id="staff", request_id="missing")
    assert not result.can_proceed
    assert not await w.repo.get_outbox_records("svc", op.operation_id)
    await w.app.update_operation(service_id="svc", operation_id=op.operation_id, staff_id="staff",
        greeting="本文1,200円/時間", introduction="\u2063", note="\u2063")
    if automatic:
        # Keep the existing explicit re-selection requirement after a blocked validation.
        await w.app.replace_targets(service_id="svc", operation_id=op.operation_id, staff_id="staff",
            selected_member_ids=tuple(w.members), reinclude_member_ids=tuple(w.members))
    result = await w.app.validate(service_id="svc", operation_id=op.operation_id, staff_id="staff", request_id="filled")
    assert result.can_proceed


def test_final_text_compat_sections_and_internal_blank_lines():
    message = SimpleNamespace(greeting="本文\n\n内部\n\n", introduction=" \u2063 ", note="\u2063")
    assert final_notification_text(message, "https://liff.line.me/example") == "本文\n\n内部\nhttps://liff.line.me/example"
    assert message.note == "\u2063"


@pytest.mark.parametrize("greeting,valid", [
    ("本文\n　【未入力：配分金】", False),
    ("【未入力：センター名】です。\r\n本文", False),
    ("本文\n　【未入力：担当者】", True),
    ("【未入力：配分金】という表示は入力欄の説明です。", True),
    ("自由編集した通知文", True),
    ("【急募：清掃】\n表示センターです。", True),
    ("【再案内：清掃】\n表示センターです。", True),
    ("【個別案内：清掃】\n表示センターです。", True),
    ("", False),
])
def test_unfilled_validation_reserves_only_generated_field_lines(greeting, valid):
    from app.application.notification_service import _message_valid
    assert _message_valid(SimpleNamespace(greeting=greeting, introduction="\u2063", note="\u2063")) is valid


@pytest.mark.parametrize("automatic", [False, True])
async def test_legacy_draft_roundtrip_and_revalidation_preserve_free_text(db, automatic):
    w = await world(db)
    message = dict(greeting="保存済みの自由文", introduction="【未入力：担当者】",
                   note="【未入力：配分金】という表示は入力欄の説明です。")
    op = await w.app.create_operation(service_id="svc", staff_id="staff", job_id="JOB-001",
        notification_type=NotificationType.NEW_JOB_MATCH, automatic_selection=automatic, **message)
    restored = await w.repo.get_operation("svc", op.operation_id)
    assert {key: getattr(restored.message, key) for key in message} == message
    await w.app.replace_targets(service_id="svc", operation_id=op.operation_id, staff_id="staff", selected_member_ids=tuple(w.members))
    result = await w.app.validate(service_id="svc", operation_id=op.operation_id, staff_id="staff", request_id="legacy")
    assert result.can_proceed
    assert (await w.repo.get_operation("svc", op.operation_id)).message == restored.message

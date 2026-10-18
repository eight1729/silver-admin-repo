"""Offline migak contract coverage through HTTP and the existing notification flow."""
import json
from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import HTTPException

from app.api.routes.admin import _translate
from app.domain.errors.errors import ExternalSystemUnavailableError, ExternalTargetLimitExceededError
from app.domain.models.external_business import JobSearchQuery
from app.domain.enums.notification_type import NotificationType
from test_admin_ic_external_business import gateway, json_handler, JOB_ITEM, ORG
from test_automatic_notification import world, prepare, validate, send
from test_admin_state_recovery import db


def candidate(i=0):
    return dict(external_member_id=f"m-{i}", display_label="Test", eligible=True,
                reason_codes=[], member_number=str(i).zfill(4), recommendation_level=5,
                distance_km=1.25, phone_last4=None, mobile_last4=None)


@pytest.mark.parametrize("count", [100, 300, 301, 500, 501, 1001, 1500])
async def test_complete_candidate_contract(count):
    provider, calls = gateway(json_handler([candidate(i) for i in range(count)]))
    rows = await provider.list_candidate_members(external_organization_id=ORG, external_job_id="job-1")
    assert len(rows) == count
    assert str(calls[0].url.query, "ascii") == "all=true"
    assert rows[-1].external_member_id == f"m-{count-1}"
    assert rows[0].distance_km == 1.25


@pytest.mark.parametrize("number", ["0001", "000001", "9" * 5000, None])
@pytest.mark.parametrize("level", [1, 2, 3, 4, 5, None])
def test_candidate_identity_and_level(number, level):
    from app.adapter.external_business_http import HttpExternalBusinessGateway
    row = HttpExternalBusinessGateway._candidate(dict(candidate(), member_number=number, recommendation_level=level))
    assert row.member_number == number and row.recommendation_level == level


@pytest.mark.parametrize("field,value", [
    ("member_number", 1234), ("member_number", "１２３４"), ("member_number", ""),
    ("recommendation_level", 0), ("recommendation_level", 6), ("recommendation_level", True),
    ("recommendation_level", "5"), ("recommendation_level", 5.0),
    ("distance_km", "1.2"), ("distance_km", True), ("distance_km", float("nan")),
])
def test_invalid_candidate_mapping_fails_closed(field, value):
    from app.adapter.external_business_http import HttpExternalBusinessGateway
    with pytest.raises(ExternalSystemUnavailableError):
        HttpExternalBusinessGateway._candidate(dict(candidate(), **{field: value}))


@pytest.mark.parametrize("distance", [None, 0, 12.75])
def test_optional_candidate_fields(distance):
    from app.adapter.external_business_http import HttpExternalBusinessGateway
    payload = candidate()
    payload.pop("member_number")
    payload.pop("recommendation_level")
    row = HttpExternalBusinessGateway._candidate(dict(payload, distance_km=distance))
    assert row.member_number is None and row.recommendation_level is None
    assert row.distance_km == distance


@pytest.mark.parametrize("value,expected", [
    ("2026-10-16T15:00:00Z", datetime(2026, 10, 16, 15, tzinfo=timezone.utc)),
    ("2026-10-16T15:00:00+00:00", datetime(2026, 10, 16, 15, tzinfo=timezone.utc)),
    (None, None), ("bad", None), (123, None), ("2026-10-16", None),
    ("2026-10-16T15:00:00", None), ("2026-10-17T00:00:00+09:00", None),
])
async def test_created_at_list_and_detail(value, expected):
    payload = dict(JOB_ITEM, created_at=value)
    provider, _ = gateway(json_handler(dict(items=[payload])))
    page = await provider.search_jobs(external_organization_id=ORG, query=JobSearchQuery())
    provider, _ = gateway(json_handler(payload))
    detail = await provider.get_job_detail(external_organization_id=ORG, external_job_id="job-1")
    assert page.items[0].created_at == detail.created_at == expected
    assert detail.updated_at is not None  # Never substitute updated_at.


@pytest.mark.parametrize("mobile,expected", [("0123", "0123"), (None, None), (1234, None),
    ("123", None), ("12345", None), ("１２３４", None), ("abcd", None)])
async def test_summary_mobile_does_not_fall_back_to_home(mobile, expected):
    provider, _ = gateway(json_handler(dict(external_member_id="m-0", display_label="Test",
        mobile_last4=mobile, phone_last4="9999")))
    row = await provider.get_member_summary(external_organization_id=ORG, external_member_id="m-0")
    assert row.mobile_phone_last4 == expected and row.display_label == "Test"


@pytest.mark.parametrize("number", ["1234", "123456", "0001", "000001", "9" * 5000],
                         ids=["four-digits", "six-digits", "leading-zero-four", "leading-zero-six", "huge"])
async def test_summary_member_number_preserves_confirmed_response_id(number):
    provider, _ = gateway(json_handler(dict(external_member_id=number, display_label="Test")))
    row = await provider.get_member_summary(external_organization_id=ORG, external_member_id=number)
    assert row.member_number == number


@pytest.mark.parametrize("number,outside_candidates", [
    ("1234", False), ("123456", False), ("0001", False), ("000001", False),
    ("9" * 100, False), ("000001", True),
])
async def test_http_summary_confirmation_number_does_not_change_send_decision(db, number, outside_candidates):
    from app.schemas.admin import AdminConfirmationResponse

    w = await world(db, 1)
    w.members[:] = [number]
    w.linked.clear()
    w.linked[number] = True
    w.external.candidate_members_result = [replace(w.external.candidate_members_result[0],
        external_member_id=number, member_number=number)]
    op = await prepare(w)
    if outside_candidates:
        w.external.candidate_members_result = []
        w.blocked.add(number)
    before = await validate(w, op)
    saved = await w.app.get_operation("svc", op)
    provider, calls = gateway(json_handler(dict(external_member_id=number,
        display_label="Test", mobile_last4="0123", phone_last4="9999")))
    w.app._external = provider
    view = await w.app.confirmation("svc", op)
    response = AdminConfirmationResponse(**view).model_dump(mode="json")
    assert response["targets"][0]["member_number"] == number
    assert response["targets"][0]["mobile_phone_last4"] == "0123"
    assert len(calls) == 1 and calls[0].url.path.endswith("members:summary")
    assert json.loads(calls[0].content) == {"external_member_id": number}
    for field in ("initial_count", "selected_count", "sendable_count", "excluded_count",
                  "can_send", "confirmation_token", "requires_revalidation"):
        assert view[field] == before[field]
    assert view["targets"][0]["disposition"] == before["targets"][0]["disposition"]
    assert view["targets"][0]["reason"] == before["targets"][0]["reason"]
    assert await w.app.get_operation("svc", op) == saved
    if outside_candidates:
        assert view["excluded_count"] == 1 and view["sendable_count"] == 0
        assert not view["can_send"] and view["confirmation_token"] is None
    else:
        assert view["can_send"] and view["confirmation_token"] is not None
    assert not await w.repo.get_outbox_records("svc", op)


async def test_missing_created_at_and_mobile_remain_unknown():
    provider, _ = gateway(json_handler(JOB_ITEM))
    detail = await provider.get_job_detail(external_organization_id=ORG, external_job_id="job-1")
    assert detail.created_at is None
    provider, _ = gateway(json_handler(dict(external_member_id="m-0", phone_last4="9999")))
    row = await provider.get_member_summary(external_organization_id=ORG, external_member_id="m-0")
    assert row.mobile_phone_last4 is None


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_summary_http_failure_is_not_displayed_as_identity(status):
    provider, _ = gateway(json_handler(dict(external_member_id="m-0", mobile_last4="0123"), status))
    with pytest.raises(ExternalSystemUnavailableError):
        await provider.get_member_summary(external_organization_id=ORG, external_member_id="m-0")


def http_world(w):
    def handler(request):
        path = request.url.path
        if path.endswith("candidate-members"):
            assert request.url.query == b"all=true"
            return httpx.Response(200, json=[candidate(i) for i in range(len(w.members))])
        if path.endswith("validate-targets"):
            ids = json.loads(request.content)["external_member_ids"]
            assert len(ids) <= 500
            return httpx.Response(200, json=dict(external_job_id="JOB-001", job_eligible=True,
                current_job_version="v1", job_reason_code=None, validated_at="2026-10-17T00:00:00Z",
                members=[dict(external_member_id=m, eligible=True, reason_code=None) for m in ids]))
        if path.endswith("members:summary"):
            return httpx.Response(200, json=dict(external_member_id=json.loads(request.content)["external_member_id"],
                display_label="Test", mobile_last4="0123", phone_last4="9999"))
        return httpx.Response(200, json=dict(JOB_ITEM, external_job_id="JOB-001"))
    provider, calls = gateway(handler)
    w.app._external = provider
    w.app.notification_service._external_business_gateway = provider
    return calls


async def test_http_full_set_selection_validation_and_send(db):
    w = await world(db, 1001)
    calls = http_world(w)
    op = await prepare(w)
    assert [len(c) for c in w.calls[:3]] == [500, 500, 1]
    saved = await w.app.get_operation("svc", op)
    assert {t.member_id for t in saved.targets if t.selected} == {f"m-{i}" for i in range(901, 1001)}
    view = await validate(w, op)
    # migak's response identity is also its display member number.
    assert all(row["member_number"] == row["member_id"] and row["mobile_phone_last4"] == "0123"
               for row in view["targets"])
    summary_calls = [r for r in calls if r.url.path.endswith("members:summary")]
    assert len(summary_calls) == 100
    assert {json.loads(r.content)["external_member_id"] for r in summary_calls} == {f"m-{i}" for i in range(901, 1001)}
    await send(w, op, view["confirmation_token"])
    assert w.dispatched
    assert len([r for r in calls if r.url.path.endswith("candidate-members")]) >= 5


@pytest.mark.parametrize("count", [500, 501])
@pytest.mark.parametrize("automatic", [False, True])
async def test_validation_limit_after_manual_edit(db, count, automatic):
    w = await world(db, count)
    calls = http_world(w)
    if automatic:
        op = await prepare(w)
    else:
        result = await w.app.create_operation(service_id="svc", staff_id="staff", job_id="JOB-001",
            notification_type=NotificationType.NEW_JOB_MATCH, greeting="hello", introduction="job", note="note")
        op = result.operation_id
    await w.app.replace_targets(service_id="svc", operation_id=op, staff_id="staff", selected_member_ids=tuple(w.members))
    assert sum(t.selected for t in (await w.app.get_operation("svc", op)).targets) == count
    if count == 500:
        await w.app.validate(service_id="svc", operation_id=op, staff_id="staff", request_id="v")
        assert any(r.url.path.endswith("validate-targets") for r in calls)
    else:
        with pytest.raises(ExternalTargetLimitExceededError):
            await w.app.validate(service_id="svc", operation_id=op, staff_id="staff", request_id="v")
        assert not any(r.url.path.endswith("validate-targets") for r in calls)
        assert (await w.app.get_operation("svc", op)).operation.status.value != "validating"
        if not automatic:
            with pytest.raises(ExternalTargetLimitExceededError):
                await send(w, op, None)
            assert not any(r.url.path.endswith("validate-targets") for r in calls)
        assert not await w.repo.get_outbox_records("svc", op)
        assert not await w.repo.get_deliveries("svc", op)
        await w.app.replace_targets(service_id="svc", operation_id=op, staff_id="staff",
                                    selected_member_ids=tuple(w.members)[:500])
        await w.app.validate(service_id="svc", operation_id=op, staff_id="staff", request_id="reduced")
        validation_calls = [r for r in calls if r.url.path.endswith("validate-targets")]
        assert len(validation_calls) == 1
        assert len(json.loads(validation_calls[0].content)["external_member_ids"]) == 500


async def test_limit_guard_precedes_token_and_http_request():
    provider, calls = gateway(json_handler({}))
    async def unexpected_token():
        pytest.fail("over-limit validation must not mint a token")
    provider._token = unexpected_token
    with pytest.raises(ExternalTargetLimitExceededError):
        await provider.validate_notification_targets(external_organization_id=ORG,
            external_job_id="job-1", expected_job_version="v1",
            external_member_ids=[f"m-{i}" for i in range(501)])
    assert calls == []


def test_limit_error_has_safe_api_code():
    with pytest.raises(HTTPException) as error:
        _translate(ExternalTargetLimitExceededError("private detail"))
    assert error.value.status_code == 422
    assert error.value.detail == {"error": "external_target_limit_exceeded"}


async def test_second_line_batch_failure_never_returns_partial_candidates(db):
    from app.application.admin_service import AdminDependencyUnavailableError
    w = await world(db, 1001)
    http_world(w)
    original = w.app._line_internal_client.batch_get_linkages
    async def fail_second(request):
        if w.calls:
            raise ValueError("offline")
        return await original(request)
    w.app._line_internal_client.batch_get_linkages = fail_second
    with pytest.raises(AdminDependencyUnavailableError):
        await w.app.automatic_selection("svc", "JOB-001")

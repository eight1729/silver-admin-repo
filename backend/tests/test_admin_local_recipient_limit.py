"""Real operation validation/reservation against disposable in-memory SQL only."""
from dataclasses import replace

import pytest

from app.application.notification_service import (
    CreateNotificationOperationCommand, NotificationTargetInput,
    ReplaceNotificationTargetsCommand, SendNotificationOperationCommand, OperationNotSendableError,
)
from app.domain.enums.notification_type import NotificationType
from app.domain.models.notification import MemberValidationResult, NotificationValidationResult
from app.domain.models.external_business import CandidateMember
from app.domain.enums.enums import DeliveryStatus
from app.adapter.local_inline_notification_queue import LocalInlineNotificationQueue
from app.runtime.admin_line import build_production_admin_application
from app.testing.local_integration import _build_external_business_fake
from test_admin_state_recovery import db, NOW
from test_admin_environment import complete_settings
from test_admin_send_capability import Client, capability


@pytest.mark.asyncio
@pytest.mark.parametrize("environment,count,skip,ready,cap_limit,allowed", [
    ("local", 10, 0, True, None, True),
    ("local", 11, 0, True, None, False),
    ("local", 11, 1, True, 10, False),
    ("production", 11, 0, True, None, True),
    ("local", 10, 0, False, 10, False),
    ("local", 10, 0, True, 9, False),
])
async def test_selected_limit_before_delivery_outbox_and_dispatch(db, environment, count, skip, ready, cap_limit, allowed):
    members = [f"recipient-{i}" for i in range(count)]
    external = _build_external_business_fake()
    external.candidate_members_result = [CandidateMember(m, "Offline member", True, (), None) for m in members]
    external.validation_result = NotificationValidationResult("JOB-001", True, "v1", None,
        tuple(MemberValidationResult(m, True, None) for m in members), NOW, None)
    application, boundary, _ = build_production_admin_application(
        runtime_settings=complete_settings(app_env=environment), engine=db, client=object(),
        external_business_gateway=external, queue_gateway=LocalInlineNotificationQueue(),
        service_id="svc", organization_id="org-fake-silver-001", runner_service_ids=("svc",))
    service = application.notification_service
    service._clock = lambda: NOW
    cap = Client(capability("staging_live" if environment == "local" else "production_live", ready, cap_limit))
    service._reservation_guard.client = cap
    dispatched = []
    async def capture(**kwargs):
        dispatched.append(kwargs)
    service._queue_gateway.register_handler(capture)
    operation = await service.create_operation(CreateNotificationOperationCommand(
        service_id="svc", job_id="JOB-001", job_version="v1", notification_type=NotificationType.NEW_JOB_MATCH,
        greeting="hello", introduction="job", note="note", created_by_staff_id="staff"))
    await service.replace_targets(ReplaceNotificationTargetsCommand("svc", operation.operation_id,
        tuple(NotificationTargetInput(m, True, i >= skip, None, None) for i, m in enumerate(members))))
    command = SendNotificationOperationCommand("svc", operation.operation_id, "staff", "offline-request")
    repo = boundary.repository
    if allowed:
        await service.send_operation(command)
        assert len(await repo.get_outbox_records("svc", operation.operation_id)) == count - skip
        deliveries = await repo.get_deliveries("svc", operation.operation_id)
        assert sum(d.status is DeliveryStatus.PENDING for d in deliveries) == count - skip
        await service.send_operation(command)
        assert await repo.get_deliveries("svc", operation.operation_id) == deliveries
        assert len(dispatched) == 1
    else:
        with pytest.raises(OperationNotSendableError) as rejected:
            await service.send_operation(command)
        if count > 10:
            assert str(rejected.value) == "local_recipient_limit_exceeded"
            assert cap.calls == 0
        assert not dispatched
        assert await repo.get_deliveries("svc", operation.operation_id) == ()
        assert await repo.get_outbox_records("svc", operation.operation_id) == ()
        saved = await repo.get_operation("svc", operation.operation_id)
        assert saved.send_requested_at is None
        assert saved.validation_snapshot["selected_target_count"] == count

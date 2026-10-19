"""Small regression tests for issues found in Phase 5 end review."""
from dataclasses import replace
from uuid import uuid4

import pytest

from app.domain.errors.admin_notification_repository import ReservedNotificationMutationError
from app.domain.models.admin_notification import NotificationAuditEvent
from app.application.notification_service import (
    NotificationService, CreateNotificationOperationCommand, NotificationTargetInput,
    ReplaceNotificationTargetsCommand, SendNotificationOperationCommand,
)
from app.domain.enums.notification_type import NotificationType
from app.adapter.local_inline_notification_queue import LocalInlineNotificationQueue
from test_admin_state_recovery import db, seed, NOW


@pytest.mark.asyncio
async def test_edit_between_validation_and_reservation_cannot_store_old_snapshot(db):
    repo, _, old, items = await seed(db, reserved=False)
    await repo.update_operation("svc", old.operation_id, replace(old, message_hash="edited"))
    with pytest.raises(ReservedNotificationMutationError):
        await repo.begin_send_attempt("svc", old.operation_id, [], items,
            NotificationAuditEvent(uuid4(), old.operation_id, "send_requested", "staff", {}, NOW),
            send_requested_at=NOW, expected_operation=old)
    assert await repo.get_outbox_records("svc", old.operation_id) == ()
    assert (await repo.get_operation("svc", old.operation_id)).send_requested_at is None


@pytest.mark.asyncio
async def test_validation_to_reservation_still_works_with_sql_snapshot(db):
    from app.testing.local_integration import _build_external_business_fake
    repo, _, _, _ = await seed(db, reserved=False)
    service = NotificationService(repository=repo, external_business_gateway=_build_external_business_fake(),
        queue_gateway=LocalInlineNotificationQueue(), clock=lambda: NOW,
        organization_id_resolver=lambda _: "org-fake-silver-001", persist_line_subjects=False)
    op = await service.create_operation(CreateNotificationOperationCommand(
        service_id="svc", job_id="JOB-001", job_version="v1", notification_type=NotificationType.NEW_JOB_MATCH,
        greeting="hello", introduction="job", note="note", created_by_staff_id="staff"))
    await service.replace_targets(ReplaceNotificationTargetsCommand("svc", op.operation_id,
        (NotificationTargetInput("M001", True, True, None, None),)))
    reserved = await service.send_operation(SendNotificationOperationCommand("svc", op.operation_id, "staff", "request"))
    assert reserved.send_requested_at == NOW
    outbox = await repo.get_outbox_records("svc", op.operation_id)
    assert len(outbox) == 1 and outbox[0].business_message == reserved.message
    assert (await service.send_operation(SendNotificationOperationCommand("svc", op.operation_id, "staff", "retry"))).send_requested_at == NOW
    assert await repo.get_outbox_records("svc", op.operation_id) == outbox


def test_runner_ownership_is_required_separately_from_scope_mapping():
    import inspect
    from app.runtime.admin_line import build_production_admin_application
    assert inspect.signature(build_production_admin_application).parameters["runner_service_ids"].default is inspect.Parameter.empty


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["crash", "optout_race"])
async def test_cross_repo_stale_admin_to_recovered_line_terminal(db, scenario):
    """Exchange only the current strict contract JSON; isolate the two repositories' app packages."""
    import subprocess
    import json
    import sys
    from pathlib import Path
    from datetime import timedelta
    from app.application.admin_line_dispatch import AdminLineOutboxDispatcher, AdminLineResultReconciler
    from app.application.admin_notification_runner import AdminNotificationRunner
    from app.contracts.admin_line_internal_v1 import NotificationResult
    from app.domain.models.admin_notification import NotificationOutboxState
    from app.domain.enums.enums import OperationStatus
    line_backend = Path(__file__).resolve().parents[3] / "silver-line-repo" / "backend"
    if not line_backend.is_dir():
        pytest.skip("cross-repository verification requires the sibling LINE checkout")
    script = r'''
import os, sys, asyncio, json
from datetime import timedelta
os.environ['DATABASE_URL']='postgresql://unused/unused'
os.environ['APP_ENV']='local'
from pydantic_settings import DotEnvSettingsSource
DotEnvSettingsSource._read_env_files=lambda self: {}
sys.path.insert(0, 'tests')
import httpx
from pydantic import SecretStr
from test_line_command_recovery_snapshot import Database, Provider, runtime, NOW
from app.schemas.line_internal_contract import NotificationCommand
from app.adapter.line_messaging_credentials import SettingsLineMessagingCredentialResolver
from app.adapter.canonical_deep_link import SettingsCanonicalDeepLinkResolver
from app.application.line_command_recovery import LineCommandRecoveryRunner
from app.application.line_notification_result_service import LineNotificationResultService
from app.application.line_recipient_service import LineRecipientService
from app.db.line_recipient_store import SqlAlchemyLineRecipientStore
from app.domain.models.line_recipient import LinkedRecipient
command=NotificationCommand.model_validate_json(sys.stdin.read())
async def main():
    db=Database()
    provider=Provider()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        current=[NOW]
        commands, deliveries, pipeline=runtime(db,client,clock=lambda:current[0])
        from app.adapter.admin_business_scope import SettingsAdminBusinessScopeResolver
        scopes=SettingsAdminBusinessScopeResolver({command.scope.service_id:command.scope.organization_id})
        commands._scopes=scopes
        await commands.accept_command(command)
        # Replay of the same Admin intent must not allocate another command.
        await commands.accept_command(command)
        store=SqlAlchemyLineRecipientStore(db)
        linkage=await store.save(LinkedRecipient(command.scope.organization_id,command.scope.service_id,
                                        command.external_member_id,'offline-subject'))
        await store.update_preferences(linkage, job_notifications_enabled=True, center_notifications_enabled=False)
        from sqlalchemy import insert
        from app.db.tables import line_recipient_states
        await db.execute(insert(line_recipient_states).values(organization_id=command.scope.organization_id,
            service_id=command.scope.service_id, line_subject='offline-subject',
            external_member_id=command.external_member_id, version=command.linkage_version))
        def configure(pipeline, base):
            pipeline._commands._scopes=scopes
            pipeline._recipients=LineRecipientService(store)
            pipeline._sender._credential_resolver=SettingsLineMessagingCredentialResolver({
                command.scope.organization_id:{command.scope.service_id:SecretStr('offline-token')}})
            pipeline._deep_links=SettingsCanonicalDeepLinkResolver({
                command.scope.organization_id:{command.scope.service_id:'https://liff.line.me/'+base}})
        configure(pipeline,'before')
        pending=None
        if sys.argv[1]=='crash':
            async def crash(*args,**kwargs): raise RuntimeError('after provider acceptance')
            deliveries.mark_sent=crash
            try: await pipeline.process_command(command.command_id)
            except RuntimeError: pass
            current[0]+=timedelta(seconds=31)
            commands, deliveries, restarted=runtime(db,client,clock=lambda:current[0])
            configure(restarted,'after')
            await LineCommandRecoveryRunner(commands=commands,pipeline=restarted).run_cycle()
        else:
            provider.block=asyncio.Event()
            task=asyncio.create_task(pipeline.process_command(command.command_id))
            while not provider.requests: await asyncio.sleep(0)
            await store.update_preferences(linkage,job_notifications_enabled=False,center_notifications_enabled=False)
            _, _, competitor=runtime(db,client,clock=lambda:current[0])
            configure(competitor,'after')
            pending=await competitor.process_command(command.command_id)
            assert pending.status.value=='pending'
            provider.block.set()
            await task
        result=await LineNotificationResultService(commands=commands,deliveries=deliveries).get_result(command.command_id)
        assert result.status.value=='sent'
        assert len(provider.accepted)==1 and len(provider.requests)==1
        assert await commands.list_recoverable_commands(50)==()
        print(json.dumps(dict(pending=pending.model_dump(mode='json') if pending else None,final=result.model_dump(mode='json'))))
    db.connection.close()
    db.engine.dispose()
asyncio.run(main())
'''
    repo, now, op, items = await seed(db)
    from sqlalchemy import update
    from app.db.admin_tables import admin_notification_outbox
    await db.execute(update(admin_notification_outbox).values(linkage_version="offline-cross-repo-version"))
    await repo.claim_outbox_records("svc", op.operation_id)
    now[0] += timedelta(seconds=60)
    class Client:
        polls = 0
        child_error = None
        async def submit_notification_command(self, command):
            assert command.command_id == items[0].command_id
            completed = subprocess.run([sys.executable, "-B", "-c", script, scenario], cwd=line_backend,
                input=command.model_dump_json(), text=True, capture_output=True, timeout=30)
            self.child_error = completed.stderr if completed.returncode else None
            assert completed.returncode == 0, completed.stderr
            payload = json.loads(completed.stdout)
            self.result = NotificationResult.model_validate(payload["final"])
            self.pending = NotificationResult.model_validate(payload["pending"]) if payload["pending"] else None
            return self.pending or self.result
        async def get_notification_result(self, command_id):
            self.polls += 1
            return self.pending if self.polls == 1 and self.pending else self.result
    client = Client()
    reconciler = AdminLineResultReconciler(repository=repo, line_client=client)
    runner = AdminNotificationRunner(repository=repo, service_ids=["svc"],
        dispatcher=AdminLineOutboxDispatcher(repository=repo, line_client=client), reconciler=reconciler)
    await runner.run_cycle()
    assert client.child_error is None, client.child_error
    if scenario == "optout_race":
        assert (await repo.get_operation("svc", op.operation_id)).status is OperationStatus.SENDING
        assert (await repo.get_outbox_records("svc", op.operation_id))[0].state is NotificationOutboxState.ACCEPTED
        now[0] += timedelta(seconds=61)
        await runner.run_cycle()  # finish cursor page
        await runner.run_cycle()  # next sweep observes the terminal result
    first = await repo.get_operation("svc", op.operation_id)
    assert first.status is OperationStatus.COMPLETED and first.completed_at is not None
    assert (await repo.get_outbox_records("svc", op.operation_id))[0].state is NotificationOutboxState.RECONCILED
    await reconciler.reconcile_operation(service_id="svc", operation_id=op.operation_id)
    assert (await repo.get_operation("svc", op.operation_id)).completed_at == first.completed_at
    assert client.polls == (2 if scenario == "optout_race" else 1)

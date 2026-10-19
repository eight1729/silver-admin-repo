from types import SimpleNamespace
from dataclasses import replace
import pytest
from test_admin_state_recovery import db
from test_automatic_notification import world, prepare, validate, send
from app.application.notification_service import OperationNotSendableError
from app.application.admin_line_dispatch import AdminLineOutboxDispatcher


@pytest.mark.asyncio
async def test_generation_changes_invalidate_confirmation_then_freeze_outbox(db):
    w = await world(db)
    op = await prepare(w)
    old = await validate(w, op)
    original = w.app._line_internal_client.batch_get_linkages
    current = ['new-generation']
    async def lookup(request):
        result = await original(request)
        for item in result['items']:
            if item['line_linked']: item['linkage_version'] = current[0]
        return result
    w.app._line_internal_client.batch_get_linkages = lookup
    with pytest.raises(OperationNotSendableError):
        await send(w, op, old['confirmation_token'])
    assert not await w.repo.get_outbox_records('svc', op)
    fresh = await validate(w, op)
    await send(w, op, fresh['confirmation_token'])
    rows = await w.repo.get_outbox_records('svc', op)
    assert rows and all(row.linkage_version == 'new-generation' for row in rows)
    current[0] = 'relinked-again'
    reloaded = await w.repo.get_outbox_records('svc', op)
    assert all(AdminLineOutboxDispatcher._command(row).linkage_version == 'new-generation' for row in reloaded)


@pytest.mark.asyncio
async def test_missing_generation_blocks_only_sendable_members(db):
    w = await world(db)
    op = await prepare(w)
    original = w.app._line_internal_client.batch_get_linkages
    async def lookup(request):
        result = await original(request)
        for item in result['items']: item['linkage_version'] = None
        return result
    w.app._line_internal_client.batch_get_linkages = lookup
    await validate(w, op)
    operation = await w.repo.get_operation('svc', op)
    assert not operation.validation_snapshot['can_proceed']
    assert not await w.repo.get_outbox_records('svc', op)

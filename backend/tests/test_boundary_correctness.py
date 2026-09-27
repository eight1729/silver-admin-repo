from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.adapter.line_internal_api import HttpLineInternalApiClient, LineInternalApiRetryableError, LineInternalApiPermanentError
from app.application.admin_line_dispatch import AdminLineOutboxDispatcher, AdminLineResultReconciler
from app.application.admin_service import AdminApplicationService, AdminDependencyUnavailableError
from app.contracts.admin_line_internal_v1 import LinkageStatusBatchResponse, LinkageStatusItem
from app.domain.models.external_business import CandidateMember
from app.domain.models.admin_notification import NotificationOutboxState
from test_admin_line_dispatch import Repo, Client, _outbox, _result, NOW
from test_admin_line_internal_client import _command, _result as wire_result
from test_admin_line_boundary import External


FIELDS = ('command_id', 'operation_id', 'target_id', 'external_member_id')


@pytest.mark.asyncio
@pytest.mark.parametrize('field', FIELDS)
@pytest.mark.parametrize('stage', ('post', 'get'))
async def test_identity_mismatch_cannot_apply_to_persistence(field, stage):
    item = _outbox()
    if stage == 'get':
        item = replace(item, state=NotificationOutboxState.ACCEPTED)
    repo = Repo(item)
    original_delivery, original_operation = repo.delivery, repo.operation
    result = _result(item, status='sent', reason_code=None, updated_at=NOW)
    setattr(result, field, 'other-member' if field == 'external_member_id' else uuid4())
    client = Client([result])
    if stage == 'post':
        await AdminLineOutboxDispatcher(repository=repo, line_client=client).dispatch_operation(
            service_id='svc', operation_id=item.operation_id)
        assert repo.item.state is NotificationOutboxState.RETRYABLE_FAILURE
    else:
        await AdminLineResultReconciler(repository=repo, line_client=client).reconcile_operation(
            service_id='svc', operation_id=item.operation_id)
        assert repo.item.state is NotificationOutboxState.ACCEPTED
    assert repo.delivery == original_delivery
    assert repo.operation == original_operation


@pytest.mark.asyncio
@pytest.mark.parametrize('field', FIELDS)
async def test_http_post_identity_mismatch_is_safe_retryable(field):
    command = _command()
    payload = wire_result(command)
    payload[field] = 'private-member' if field == 'external_member_id' else str(uuid4())
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(202, json=payload))) as http:
        client = HttpLineInternalApiClient(client=http, base_url='https://line.internal',
            bearer_token=SecretStr('test'), environment='production')
        with pytest.raises(LineInternalApiRetryableError) as caught:
            await client.submit_notification_command(command)
        assert str(caught.value) == 'LINE notification response identity mismatch'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 404])
async def test_http_get_command_identity_and_unchanged_404(status):
    command = _command()
    payload = wire_result(command)
    payload['command_id'] = str(uuid4())
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json=payload))) as http:
        client = HttpLineInternalApiClient(client=http, base_url='https://line.internal',
            bearer_token=SecretStr('test'), environment='production')
        expected = LineInternalApiRetryableError if status == 200 else LineInternalApiPermanentError
        with pytest.raises(expected):
            await client.get_notification_result(command.command_id)


def candidate_service(ids, *, fail_at=None, invalid=None):
    class Business(External):
        async def list_candidate_members(self, **kwargs):
            return tuple(CandidateMember(mid, str(i), True, (), None) for i, mid in enumerate(ids))
    class LinkageClient:
        calls = None
        def __init__(self): self.calls = []
        async def batch_get_linkages(self, request):
            self.calls.append(request)
            if len(self.calls) == fail_at:
                raise LineInternalApiRetryableError('unavailable')
            members = list(reversed(request.external_member_ids))
            if invalid == 'missing': members.pop()
            if invalid == 'extra': members.append('unrequested')
            if invalid == 'duplicate': members[-1] = members[0]
            if invalid == 'malformed': return {'items': [{'unexpected': True}]}
            return LinkageStatusBatchResponse(items=tuple(LinkageStatusItem(
                external_member_id=mid, line_linked=mid != 'B') for mid in members))
    client = LinkageClient()
    service = AdminApplicationService(notification_service=SimpleNamespace(),
        external_business_gateway=Business(), demo_service_id='svc',
        line_linked_member_ids=frozenset(), line_internal_client=client,
        organization_id_resolver=lambda service: 'org')
    return service, client


@pytest.mark.asyncio
@pytest.mark.parametrize('count,sizes', [(0, []), (1, [1]), (500, [500]),
    (501, [500, 1]), (1000, [500, 500]), (1001, [500, 500, 1])])
async def test_batch_boundaries_preserve_candidate_order(count, sizes):
    ids = [f'member-{i}' for i in range(count)]
    service, client = candidate_service(ids)
    result = await service.list_candidates('svc', 'job')
    assert [len(call.external_member_ids) for call in client.calls] == sizes
    assert [x.member_id for x in result] == ids
    assert all(x.line_linked for x in result)


@pytest.mark.asyncio
async def test_batch_dedupes_transport_not_candidates():
    service, client = candidate_service(['A', 'A', 'B'])
    result = await service.list_candidates('svc', 'job')
    assert client.calls[0].external_member_ids == ('A', 'B')
    assert [(x.member_id, x.display_name, x.line_linked) for x in result] == [
        ('A', '0', True), ('A', '1', True), ('B', '2', False)]


@pytest.mark.asyncio
@pytest.mark.parametrize('fail_at', [2, 3])
async def test_batch_partial_failure_returns_no_candidates(fail_at):
    service, client = candidate_service([str(i) for i in range(1001)], fail_at=fail_at)
    with pytest.raises(AdminDependencyUnavailableError, match='LINE linkage lookup unavailable'):
        await service.list_candidates('svc', 'job')
    assert len(client.calls) == fail_at


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', ['missing', 'extra', 'duplicate', 'malformed'])
async def test_batch_response_must_exactly_cover_requested_members(invalid):
    service, _ = candidate_service(['A', 'B'], invalid=invalid)
    with pytest.raises(AdminDependencyUnavailableError, match='LINE linkage lookup unavailable'):
        await service.list_candidates('svc', 'job')

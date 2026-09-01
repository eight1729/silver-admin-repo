from types import SimpleNamespace
from datetime import datetime, timezone

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.runtime.admin_line import build_production_admin_application
from app.application.admin_service import AdminApplicationService
from app.domain.enums.enums import JobStatus
from app.domain.models.external_business import CandidateMember, ExternalJobDetail
from app.contracts.admin_line_internal_v1 import (
    LiffDeepLinkResponse, LinkageStatusBatchResponse, LinkageStatusItem,
)


class Queue:
    def register_handler(self, handler): self.handler = handler


def test_production_admin_composition_has_only_internal_api_line_boundary():
    queue = Queue()
    configured = Settings(
        _env_file=None,
        database_url="postgresql://unused/unused",
        app_env="production",
        admin_line_internal_api_base_url="https://line.internal",
        admin_line_internal_api_bearer_token=SecretStr("private"),
    )
    application, boundary, dispatch = build_production_admin_application(
        external_business_gateway=SimpleNamespace(),
        queue_gateway=queue,
        service_id="svc",
        organization_id="org",
        engine=object(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: None)),
        runtime_settings=configured,
    )
    notifications = application.notification_service
    assert notifications._line_sender is None
    assert notifications._line_subject_resolver is None
    assert notifications._persist_line_subjects is False
    assert application._line_internal_client is boundary.client
    assert queue.handler is dispatch
    assert not hasattr(boundary, "line_sender")


class External:
    async def get_job_detail(self, **kwargs):
        return ExternalJobDetail(
            external_job_id=kwargs["external_job_id"], title="job", description="d",
            work_location=None, work_schedule_text=None, application_deadline=None,
            required_conditions=(), status=JobStatus.PUBLISHED, version="v1",
            updated_at=datetime.now(timezone.utc), staff_notes=None,
        )
    async def list_candidate_members(self, **kwargs):
        return (CandidateMember("member-1", "Member", True, (), None, line_subject="must-ignore"),)


class BoundaryClient:
    def __init__(self): self.linkage_requests=[]; self.link_requests=[]
    async def batch_get_linkages(self, request):
        self.linkage_requests.append(request)
        return LinkageStatusBatchResponse(items=(LinkageStatusItem(external_member_id="member-1", line_linked=True),))
    async def resolve_deep_link(self, request):
        self.link_requests.append(request)
        return LiffDeepLinkResponse(canonical_deep_link="https://line.example/liff/jobs/job?service_id=svc")


@pytest.mark.asyncio
async def test_production_candidates_and_deep_link_come_from_line_contract():
    client=BoundaryClient()
    app=AdminApplicationService(
        notification_service=SimpleNamespace(), external_business_gateway=External(),
        demo_service_id="svc", line_linked_member_ids=frozenset(), expose_line_subjects=False,
        line_internal_client=client, organization_id_resolver=lambda service: "org",
    )
    candidates=await app.list_candidates("svc", "job")
    assert candidates[0].line_linked is True and candidates[0].line_subject is None
    link=await app.resolve_notification_link("svc", "job")
    assert link.startswith("https://line.example/")
    assert client.linkage_requests[0].scope.organization_id == "org"
    assert client.link_requests[0].job_id == "job"

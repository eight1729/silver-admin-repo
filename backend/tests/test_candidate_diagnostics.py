"""Candidate diagnostics: offline SQL/HTTP doubles, no settings or real data."""
from contextlib import asynccontextmanager
import logging
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.exc import ProgrammingError

from app.adapter.current_db_external_business import CurrentDbExternalBusinessGateway
from app.adapter.line_internal_api import HttpLineInternalApiClient
from app.contracts.admin_line_internal_v1 import ServiceOrganizationScope, LinkageStatusBatchRequest
from test_jobs_diagnostics import application, app_for, row
from app.core.candidate_diagnostics import point

PRIVATE = "PRIVATE-member-name-phone-token-SQL"
LOGGER = "uvicorn.error.admin_candidates"


class DriverError(Exception):
    sqlstate = "42703"


class Engine:
    @asynccontextmanager
    async def connect(self):
        yield self

    async def execute(self, statement):
        if self.fail:
            raise ProgrammingError(PRIVATE, {"secret": PRIVATE}, DriverError(PRIVATE))
        rows = [dict(id=UUID(int=i + 1), full_name=PRIVATE, member_code=str(i + 1),
                     recommendation_level=5) for i in range(120)]
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))


@pytest.mark.parametrize("failure", [None, "sql", "timeout", "incomplete", "http", "slow_success", "read_timeout", "malformed"])
async def test_candidate_request_boundaries_and_no_private_values(caplog, failure):
    caplog.set_level(logging.INFO, logger=LOGGER)
    engine = Engine()
    engine.fail = failure == "sql"
    provider = CurrentDbExternalBusinessGateway(engine, {"sandbox": "sumida"})
    async def job(**kwargs):
        return provider._job_summary(row())
    provider.get_job_detail = job
    calls = []
    async def transport(request):
        calls.append(request.url.path)
        if failure in {"slow_success", "read_timeout"}:
            # Virtual read wait: MockTransport does not enforce socket timeouts.
            # Verify the budget handed to the transport without sleeping 180s.
            assert request.extensions["timeout"]["read"] == 180.0
            simulated_wait = 10.1 if failure == "slow_success" else 180.1
            if simulated_wait > request.extensions["timeout"]["read"]:
                raise httpx.ReadTimeout(PRIVATE)
        if failure == "timeout":
            raise httpx.ConnectTimeout(PRIVATE)
        if failure == "malformed":
            return httpx.Response(200, json={"invalid": PRIVATE})
        if failure == "http":
            return httpx.Response(503, text=PRIVATE)
        return httpx.Response(200, json={"items": [] if failure == "incomplete" else [
            {"external_member_id": str(UUID(int=i + 1)), "line_linked": False} for i in range(120)]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as outbound:
        line = HttpLineInternalApiClient(client=outbound, base_url="https://private.invalid",
                                         bearer_token=SecretStr(PRIVATE), environment="production")
        service = application(provider)
        service._scope_resolver = SimpleNamespace(resolve=lambda _: ServiceOrganizationScope(
            organization_id="sandbox", service_id="private-service"))
        service._line_internal_client = line
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(service)), base_url="http://offline") as client:
            response = await client.get(f"/admin/jobs/{UUID(int=1)}/candidates")
        success = failure in {None, "slow_success"}
        assert response.status_code == (200 if success else 503)
        if success:
            assert len(response.json()) == 120
            assert all(not item["line_linked"] for item in response.json())
        records = [r for r in caplog.records if r.name == LOGGER]
        text = "\n".join(r.getMessage() for r in records)
        assert all(r.exc_info is None and r.stack_info is None for r in records)
        for value in (PRIVATE, "private.invalid", "sandbox", "sumida", "private-service", str(UUID(int=1))):
            assert value not in text
        assert "stage=list_candidates_start" in text
        if failure == "sql":
            assert "stage=candidate_sql_failed" in text and "sqlstate=42703" in text
            assert not calls
        else:
            assert "stage=candidate_mapping_complete count=120" in text
            assert "stage=line_batch_start request_count=120" in text
            assert "stage=line_http_start" in text
        if failure == "timeout":
            assert "cause_class=ConnectTimeout" in text and "reason_category=timeout" in text
            assert "stage=line_http_response" not in text
        elif failure == "read_timeout":
            assert "cause_class=ReadTimeout" in text and "reason_category=timeout" in text
            assert "stage=line_http_response" not in text
        elif failure == "malformed":
            assert "reason_category=contract" in text
        elif failure == "incomplete":
            assert "request_count=120 response_count=0 matched_count=0" in text
        elif failure == "http":
            assert "http_status=503" in text and "reason_category=http" in text
        elif success:
            assert "request_count=120 response_count=120 matched_count=120" in text
        # Scope resets after success AND failure. Non-candidate linkage calls stay quiet.
        caplog.clear()
        try:
            await line.batch_get_linkages(LinkageStatusBatchRequest(
                scope=ServiceOrganizationScope(organization_id="sandbox", service_id="private-service"),
                external_member_ids=(str(UUID(int=1)),)))
        except Exception:
            pass
        point("outside_scope", count=120)
        assert not [r for r in caplog.records if r.name == LOGGER]

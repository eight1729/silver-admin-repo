"""Offline checks for diagnostics removal, batch timeout and manual label SQL."""
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from app.adapter.line_internal_api import HttpLineInternalApiClient
from app.contracts.admin_line_internal_v1 import ServiceOrganizationScope
from app.domain.models.external_business import CandidateMember
from test_jobs_diagnostics import application, app_for

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("outcome", ["slow_success", "read_timeout", "incomplete", "malformed"])
async def test_batch_120_keeps_timeout_and_fail_closed_after_diagnostics_removal(outcome):
    async def job(**kwargs):
        return SimpleNamespace(external_job_id=str(UUID(int=1)))
    async def candidates(**kwargs):
        return [CandidateMember(str(UUID(int=i+1)), "架空", True, (), None,
                                member_number=f"{i+1:04}", recommendation_level=5) for i in range(120)]
    async def transport(request):
        assert request.extensions["timeout"] == {"connect": 10.0, "read": 180.0, "write": 10.0, "pool": 10.0}
        # Virtual wait: MockTransport itself does not enforce socket deadlines.
        wait = 180.1 if outcome == "read_timeout" else 10.1
        if wait > request.extensions["timeout"]["read"]:
            raise httpx.ReadTimeout("offline simulated wait")
        if outcome == "malformed":
            return httpx.Response(200, json={"unexpected": True})
        return httpx.Response(200, json={"items": [] if outcome == "incomplete" else [
            {"external_member_id": str(UUID(int=i+1)), "line_linked": False} for i in range(120)]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport), timeout=10.0) as outbound:
        service = application(SimpleNamespace(get_job_detail=job, list_candidate_members=candidates))
        service._scope_resolver = SimpleNamespace(resolve=lambda _: ServiceOrganizationScope(organization_id="sandbox", service_id="svc"))
        service._line_internal_client = HttpLineInternalApiClient(client=outbound, base_url="https://offline.invalid",
                                                                bearer_token=SecretStr("offline"), environment="production")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(service)), base_url="http://offline") as client:
            response = await client.get(f"/admin/jobs/{UUID(int=1)}/candidates")
        assert response.status_code == (200 if outcome == "slow_success" else 503)
        if outcome == "slow_success":
            assert len(response.json()) == 120
            assert response.json()[30]["member_number"] == "0031"
            assert response.json()[-1]["member_number"] == "0120"


def test_diagnostics_removed_but_jobs_diagnostics_retained():
    assert not (ROOT / "backend/app/core/candidate_diagnostics.py").exists()
    for name in ("application/admin_service.py", "adapter/current_db_external_business.py", "adapter/line_internal_api.py"):
        text = (ROOT / "backend/app" / name).read_text(encoding="utf-8")
        assert "candidate_diagnostics" not in text
        assert "candidate_point" not in text and "candidate_span" not in text
    assert (ROOT / "backend/app/core/jobs_diagnostics.py").exists()


def test_manual_label_sql_is_scoped_guarded_and_noop_on_repeat():
    text = (ROOT / "backend/manual_sql/current_db_job_labels_v1/01_update.sql").read_text(encoding="utf-8")
    assert text.count("UPDATE public.") == 1
    assert "UPDATE public.jobs j" in text
    assert "j.id=f.id AND j.job_code=f.job_code AND j.center_code='sumida'" in text
    assert "IS DISTINCT FROM ROW(f.title,f.summary,f.location_text,f.work_date_text)" in text
    assert "current_database()" in text and "REPLACE_WITH_SUMIDA_LABELS_TEST_CONSENT" in text
    assert "send_requested_at IS NOT NULL AND o.completed_at IS NULL" in text
    assert "j.created_at IS DISTINCT FROM b.created_at" in text
    assert "DISABLE TRIGGER" not in text and "SET updated_at" not in text
    assert all(text.count(code) == 1 for code in ("REC-V1-JOB-001", "REC-V1-JOB-002", "REC-V1-JOB-003"))

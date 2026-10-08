"""Jobs diagnostics with Python doubles only: no database or network."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
from types import SimpleNamespace, MappingProxyType
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.adapter.current_db_external_business import CurrentDbExternalBusinessGateway
from app.api.routes.admin import router
from app.api.admin_auth import require_admin_viewer
from app.api.admin_entry_deps import get_admin_application_service
from app.app_factory import configure_shared_infrastructure
from app.application.admin_service import AdminApplicationService
from app.core.jobs_diagnostics import jobs_failure
from app.domain.errors.errors import ExternalSystemUnavailableError
from app.domain.models.external_business import JobSearchQuery
from app.domain.ports.organization_service_scope import OrganizationServiceScopeNotConfiguredError

PRIVATE = "private-password-host-token-SQL-job-title-staff"
NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def row():
    return dict(id=UUID(int=1), title=PRIVATE, summary=PRIVATE,
                location_text=None, work_date_text=None, status="published", updated_at=NOW)


class Engine:
    def __init__(self, rows, error=None, fail_at=1):
        self.rows, self.error, self.fail_at = rows, error, fail_at
        self.calls = 0

    @asynccontextmanager
    async def connect(self):
        yield self

    async def execute(self, statement):
        self.calls += 1
        if self.error is not None and self.calls == self.fail_at:
            raise self.error
        rows = [{"total": len(self.rows)}] if self.calls == 1 else self.rows
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))


def gateway(rows, **kwargs):
    return CurrentDbExternalBusinessGateway(Engine(rows, **kwargs), {"sandbox": "sumida"})


def application(provider):
    return AdminApplicationService(
        notification_service=None, external_business_gateway=provider,
        demo_service_id=None, line_linked_member_ids=frozenset(),
        scope_resolver=SimpleNamespace(resolve=lambda _: SimpleNamespace(organization_id="sandbox")),
    )


def app_for(service, *, dependency_error=None):
    app = FastAPI()
    configure_shared_infrastructure(app, "")
    app.include_router(router)
    def staff():
        if dependency_error is not None:
            raise dependency_error
        return SimpleNamespace(service_id="private-service")
    app.dependency_overrides[require_admin_viewer] = staff
    app.dependency_overrides[get_admin_application_service] = lambda: service
    return app


def messages(caplog):
    records = [r for r in caplog.records if r.name == "uvicorn.error.admin_jobs"]
    assert all(r.exc_info is None and r.stack_info is None for r in records)
    result = "\n".join(r.getMessage() for r in records)
    for secret in (PRIVATE, "sandbox", "sumida", "private-service", str(UUID(int=1))):
        assert secret not in result
    return result


@pytest.fixture(autouse=True)
def capture_info(caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error.admin_jobs")


@pytest.mark.parametrize("count", [0, 1, 10])
async def test_success_order_batch_size_and_response_contract(caplog, count):
    service = application(gateway([MappingProxyType(row()) for _ in range(count)]))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(service)), base_url="http://offline") as client:
        response = await client.get("/admin/jobs")
    assert response.status_code == 200
    assert response.json() == [dict(job_id=str(UUID(int=1)), title=PRIVATE, location=None,
        status="published", openings=1, version=NOW.isoformat(), summary=PRIVATE,
        work_days=None, work_time=None)] * count
    lines = messages(caplog).splitlines()
    assert lines == [
        "component=admin_jobs_route operation=list_jobs_start",
        "component=admin_application operation=list_jobs_start",
        "component=current_db_business operation=search_jobs_start center_mapping_found=true",
        "component=current_db_business operation=search_jobs_count_loaded count_loaded=true",
        "component=current_db_business operation=search_jobs_rows_loaded rows_loaded=true",
        "component=current_db_business operation=job_summary_start",
        "component=current_db_business operation=job_summary_complete",
        "component=current_db_business operation=search_jobs_complete",
        "component=admin_application operation=list_jobs_complete",
        "component=admin_jobs_route operation=list_jobs_complete",
    ]


@pytest.mark.parametrize("error_type", [KeyError, TypeError, AttributeError, ValueError, OverflowError])
async def test_summary_failure_rethrows_same_exception_without_payload(caplog, monkeypatch, error_type):
    provider = gateway([row(), row()])
    error = error_type(PRIVATE)
    original = provider._job_summary
    calls = 0
    def convert(value):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise error
        return original(value)
    monkeypatch.setattr(provider, "_job_summary", convert)
    with pytest.raises(error_type) as caught:
        await provider.search_jobs(external_organization_id="sandbox", query=JobSearchQuery())
    assert caught.value is error
    log = messages(caplog)
    assert "operation=job_summary exception_class=" + error_type.__name__ in log
    assert "operation=job_summary_complete" not in log
    assert "operation=search_jobs_complete" not in log


async def test_missing_mapping_keeps_exception_and_never_queries(caplog):
    provider = gateway([])
    with pytest.raises(OrganizationServiceScopeNotConfiguredError):
        await provider.search_jobs(external_organization_id="missing", query=JobSearchQuery())
    assert provider._engine.calls == 0
    assert "operation=search_jobs_center_mapping exception_class=OrganizationServiceScopeNotConfiguredError" in messages(caplog)


class DriverError(Exception):
    sqlstate = "42703"


@pytest.mark.parametrize("fail_at", [1, 2])
async def test_query_failure_keeps_503_and_driver_metadata(caplog, fail_at):
    error = ProgrammingError(PRIVATE, {PRIVATE: PRIVATE}, DriverError(PRIVATE))
    service = application(gateway([row()], error=error, fail_at=fail_at))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(service)), base_url="http://offline") as client:
        response = await client.get("/admin/jobs")
    assert response.status_code == 503
    assert response.json() == {"detail": {"error": "service_unavailable"}}
    log = messages(caplog)
    phase = "count" if fail_at == 1 else "rows"
    assert f"operation=search_jobs_{phase}_query exception_class=ExternalSystemUnavailableError" in log
    assert "driver_exception_class=DriverError sqlstate=42703" in log


@pytest.mark.parametrize("code,expected", [("42P01", "42P01"), ("22003", "22003"),
    (PRIVATE, "unavailable"), ("42P01\n", "unavailable"), (None, "unavailable")])
def test_sqlstate_allowlist(caplog, code, expected):
    driver = DriverError(PRIVATE)
    driver.sqlstate = code
    jobs_failure("current_db_business", "job_summary", ProgrammingError(PRIVATE, {}, driver))
    assert f"sqlstate={expected}" in messages(caplog)


@pytest.mark.parametrize("error_type,status,body", [
    (ProgrammingError, 500, "internal_error"), (OperationalError, 503, "database_unavailable"),
])
async def test_dependency_failure_before_route_is_diagnosed_without_contract_change(caplog, error_type, status, body):
    error = error_type(PRIVATE, {PRIVATE: PRIVATE}, DriverError(PRIVATE))
    app = app_for(None, dependency_error=error)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://offline") as client:
        response = await client.get("/admin/jobs")
    assert response.status_code == status
    assert response.json() == {"detail": {"error": body}}
    log = messages(caplog)
    assert "component=admin_jobs_http" in log
    assert f"exception_class={error_type.__name__}" in log
    assert "component=admin_jobs_route" not in log


async def test_application_result_conversion_failure(caplog):
    async def search_jobs(**kwargs):
        return SimpleNamespace(items=None)
    with pytest.raises(TypeError):
        await application(SimpleNamespace(search_jobs=search_jobs)).list_jobs("private-service")
    assert "operation=list_jobs_response exception_class=TypeError" in messages(caplog)


async def test_route_response_conversion_failure(caplog):
    async def list_jobs(service_id):
        return (object(),)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(SimpleNamespace(list_jobs=list_jobs)),
            raise_app_exceptions=False), base_url="http://offline") as client:
        response = await client.get("/admin/jobs")
    assert response.status_code == 500
    assert "component=admin_jobs_route operation=list_jobs_response exception_class=AttributeError" in messages(caplog)


@pytest.mark.parametrize("field,value,error_type", [
    ("title", "remove", KeyError),
    ("updated_at", None, ExternalSystemUnavailableError),
    ("updated_at", NOW.replace(tzinfo=None), ExternalSystemUnavailableError),
])
async def test_real_summary_conversion_failure(caplog, field, value, error_type):
    value_row = row()
    if value == "remove":
        del value_row[field]
    else:
        value_row[field] = value
    with pytest.raises(error_type):
        await gateway([value_row]).search_jobs(external_organization_id="sandbox", query=JobSearchQuery())
    assert "operation=job_summary exception_class=" + error_type.__name__ in messages(caplog)


def test_exception_metadata_property_failure_and_pgcode_fallback(caplog):
    class UnreadableDriver(Exception):
        @property
        def sqlstate(self):
            raise RuntimeError(PRIVATE)
        pgcode = "08006"
    jobs_failure("current_db_business", "search_jobs_rows_query",
                 OperationalError(PRIVATE, {}, UnreadableDriver(PRIVATE)))
    assert "driver_exception_class=UnreadableDriver sqlstate=08006" in messages(caplog)

"""Slice B: isolated Current DB/ASGI doubles; no PostgreSQL or external calls."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from app.application import admin_service
from app.application.admin_service import AdminApplicationService, AdminDependencyUnavailableError
from app.api.routes.admin import router
from app.api.admin_auth import require_admin_viewer
from app.api.admin_entry_deps import get_admin_application_service
from app.domain.enums.enums import JobStatus
from app.domain.models.external_business import ExternalJobSummary, PagedExternalJobs
from app.domain.errors.errors import ExternalSystemUnavailableError
from app.adapter.current_db_external_business import CurrentDbExternalBusinessGateway
from fastapi import FastAPI
from test_current_db_external_business import db, NOW, J1


def service(provider):
    return AdminApplicationService(notification_service=None,
        external_business_gateway=provider, demo_service_id=None,
        line_linked_member_ids=frozenset(), scope_resolver=SimpleNamespace(
            resolve=lambda _: SimpleNamespace(organization_id="org-a")))


def job(identity, created_at=NOW):
    return ExternalJobSummary(identity, "fixture", None, None, None, None,
                              JobStatus.PUBLISHED, "preserved-version", NOW, created_at=created_at)


@pytest.mark.parametrize("count", [13, 213])
async def test_current_db_complete_collection_order_and_registration_projection(db, count):
    gateway, engine, tables = db
    engine.connection.execute(tables["jobs"].insert(), [
        dict(id=UUID(int=100 + n), title="Fixture", status="published",
             updated_at=NOW + timedelta(days=90), created_at=NOW + timedelta(days=n // 2),
             center_code="center-a") for n in range(count - 3)
    ])
    items = await service(gateway).list_jobs("service")
    assert len(items) == count
    assert len({item.external_job_id for item in items}) == count
    assert items == tuple(sorted(items, key=lambda i: (-i.created_at.timestamp(), i.external_job_id)))
    assert len(engine.statements) == (2 if count == 13 else 4)
    assert any(item.status is JobStatus.CLOSED for item in items)
    detail = await gateway.get_job_detail(external_organization_id="org-a", external_job_id=str(J1))
    assert detail.created_at == NOW - timedelta(days=10)
    assert detail.updated_at == NOW and detail.version == NOW.isoformat()


@pytest.mark.parametrize("value", [None, NOW.replace(tzinfo=None), "2026-01-01"])
def test_current_db_never_substitutes_invalid_registration(value):
    with pytest.raises(ExternalSystemUnavailableError):
        CurrentDbExternalBusinessGateway._created_at(dict(created_at=value, updated_at=NOW))


def test_current_db_registration_utc_normalization():
    assert CurrentDbExternalBusinessGateway._created_at({
        "created_at": NOW.astimezone(timezone(timedelta(hours=9)))}) == NOW


class Provider:
    def __init__(self, responses):
        self.responses = responses
        self.queries = []

    async def search_jobs(self, *, external_organization_id, query):
        self.queries.append(query)
        result = self.responses[len(self.queries) - 1]
        if isinstance(result, Exception):
            raise result
        return result


def page(items, number=1, total=None, more=False):
    return PagedExternalJobs(tuple(items), number, 200, total, more)


async def test_unknown_dates_last_and_stable_identity_order():
    p = Provider([page([job("z", None), job("b"), job("a"), job("y", None)])])
    assert [i.external_job_id for i in await service(p).list_jobs("service")] == ["a", "b", "y", "z"]


async def test_unknown_total_uses_has_next_until_complete():
    p = Provider([page([job("old", NOW)], more=True),
                  page([job("new", NOW + timedelta(days=1))], number=2)])
    assert [i.external_job_id for i in await service(p).list_jobs("service")] == ["new", "old"]
    assert [q.page for q in p.queries] == [1, 2]
    assert all(q.page_size == 200 and q.statuses is None for q in p.queries)


@pytest.mark.parametrize("responses", [
    [page([], more=True)],
    [page([job("a")], total=2)],
    [page([job("a")], more=True), page([job("a")], number=2)],
    [page([job("a"), job("a")])],
    [page([job("a")], more=True), page([job("b")], number=1)],
    [page([job("a")], total=3, more=True), page([job("b")], number=2, total=2)],
    [page([job("a")], total=1, more=True)],
    [page([job("a")], total=0)],
])
async def test_partial_or_inconsistent_collection_is_rejected(responses):
    with pytest.raises(AdminDependencyUnavailableError):
        await service(Provider(responses)).list_jobs("service")


async def test_page_limit_is_error_not_partial_success(monkeypatch):
    monkeypatch.setattr(admin_service, "MAX_JOB_PAGES", 2)
    p = Provider([page([job("a")], more=True), page([job("b")], number=2, more=True)])
    with pytest.raises(AdminDependencyUnavailableError):
        await service(p).list_jobs("service")
    assert len(p.queries) == 2


async def response_for(provider):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_admin_viewer] = lambda: SimpleNamespace(service_id="service")
    app.dependency_overrides[get_admin_application_service] = lambda: service(provider)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline") as client:
        return await client.get("/admin/jobs")


async def test_api_iso_projection_and_missing_date_preserve_version():
    response = await response_for(Provider([page([job("known"), job("unknown", None)])]))
    assert response.status_code == 200
    known, unknown = response.json()
    assert datetime.fromisoformat(known["created_at"]) == NOW
    assert unknown["created_at"] is None
    assert known["version"] == unknown["version"] == "preserved-version"


async def test_current_db_detail_api_registration_projection(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_admin_viewer] = lambda: SimpleNamespace(service_id="service")
    app.dependency_overrides[get_admin_application_service] = lambda: service(db[0])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline") as client:
        response = await client.get(f"/admin/jobs/{J1}")
    assert response.status_code == 200
    assert datetime.fromisoformat(response.json()["created_at"]) == NOW - timedelta(days=10)
    assert response.json()["version"] == NOW.isoformat()


async def test_invalid_provider_registration_is_unavailable():
    response = await response_for(Provider([page([job("invalid", NOW.replace(tzinfo=None))])]))
    assert response.status_code == 503


async def test_later_page_failure_keeps_existing_503_contract():
    response = await response_for(Provider([page([job("a")], more=True),
                                         ExternalSystemUnavailableError("unavailable")]))
    assert response.status_code == 503
    assert response.json() == {"detail": {"error": "service_unavailable"}}


def test_admin_openapi_artifact_is_generated_and_registration_optional():
    from scripts.export_application_openapi import OUTPUT, serialize, schema
    assert OUTPUT.read_text(encoding="utf-8") == serialize()
    schemas = schema()["components"]["schemas"]
    for name in ("AdminJobSummaryResponse", "AdminJobDetailResponse"):
        assert "created_at" not in schemas[name]["required"]
        assert {"type": "string", "format": "date-time"} in schemas[name]["properties"]["created_at"]["anyOf"]

"""Execute adapter queries on an isolated SQLAlchemy relational test double.

SQLite is test-only. The connection double supplies timezone-aware timestamps
as PostgreSQL does; no settings, actual DB, .env or network are used here.
"""

from contextlib import asynccontextmanager
from dataclasses import fields
from datetime import datetime, timedelta, timezone
import inspect
from types import SimpleNamespace
from typing import get_type_hints
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import Column, MetaData, Table, create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

from app.adapter.current_db_external_business import (
    CurrentDbExternalBusinessGateway, _jobs, _members, _recommendations,
)
from app.api import admin_internal_deps
from app.api.routes.admin_internal import router
from app.domain.enums.enums import MemberVerificationStatus as Status
from app.domain.errors.errors import (
    ExternalBusinessNotConfiguredError, ExternalJobNotFoundError,
    ExternalMemberNotFoundError, ExternalSystemUnavailableError,
)
from app.domain.models.external_business import (
    ExternalJobDetail, ExternalJobSummary, MemberVerificationInput,
)
from app.domain.ports.external_business import ExternalBusinessGateway
from app.domain.ports.organization_service_scope import OrganizationServiceScopeNotConfiguredError

M1, M2, M3 = [UUID(int=i) for i in (1, 2, 3)]
J1, J2, J3, J4 = [UUID(int=i) for i in (11, 12, 13, 14)]
NOW = datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=timezone.utc)


class QueryEngine:
    def __init__(self, connection):
        self.connection = connection
        self.statements = []
        self.error = None

    @asynccontextmanager
    async def connect(self):
        yield self

    async def execute(self, statement):
        self.statements.append(statement)
        if self.error:
            raise self.error
        rows = [dict(row) for row in self.connection.execute(statement).mappings()]
        for row in rows:
            if isinstance(row.get("updated_at"), datetime):
                row["updated_at"] = row["updated_at"].replace(tzinfo=timezone.utc)
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))


@pytest.fixture
def db():
    metadata = MetaData()
    tables = {
        clause.name: Table(clause.name, metadata, *(Column(c.name, c.type) for c in clause.c), schema="public")
        for clause in (_members, _jobs, _recommendations)
    }
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
        metadata.create_all(connection)  # Test-only schema; never provision Current DB.
        connection.execute(tables["members"].insert(), [
            {"id": M1, "member_code": "0007", "full_name": "Test Name", "center_code": "center-a"},
            {"id": M2, "member_code": "0007", "full_name": "Other Name", "center_code": "center-b"},
            {"id": M3, "member_code": "0008", "full_name": "No Jobs", "center_code": "center-a"},
        ])
        connection.execute(tables["jobs"].insert(), [
            {"id": job_id, "title": "Job", "summary": "Description", "location_text": "Place",
             "work_date_text": "Schedule", "status": status, "updated_at": NOW, "center_code": center}
            for job_id, center, status in [
                (J1, "center-a", "published"), (J2, "center-b", "published"),
                (J3, "center-a", "published"), (J4, "center-a", "closed"),
            ]
        ])
        connection.execute(tables["job_recommendation_flags"].insert(), [
            {"member_id": member, "job_id": job, "center_code": center, "is_recommended": flag}
            for member, job, center, flag in [
                (M1, J1, "center-a", True), (M1, J2, "center-a", True),
                (M1, J3, "center-a", False), (M1, J4, "center-a", True),
                (M1, J3, "center-b", True), (M2, J3, "center-a", True),
            ]
        ])
        query_engine = QueryEngine(connection)
        gateway = CurrentDbExternalBusinessGateway(query_engine, {"org-a": "center-a", "org-b": "center-b"})
        yield gateway, query_engine, tables
    engine.dispose()


@pytest.mark.parametrize("number,name,status", [
    ("0007", "Test Name", Status.UNIQUE_MATCH), ("7", "Test Name", Status.NO_MATCH),
    ("0007", " Test Name", Status.NO_MATCH), ("0007", "Other Name", Status.NO_MATCH),
    ("missing", "Test Name", Status.NO_MATCH), ("0007' OR 1=1 --", "Test Name", Status.NO_MATCH),
])
async def test_exact_verification_and_scope(db, number, name, status):
    result = await db[0].verify_member(
        external_organization_id="org-a", verification=MemberVerificationInput(number, name),
    )
    assert result.status is status
    assert result.external_member_id == (str(M1) if status is Status.UNIQUE_MATCH else None)
    assert result.external_member_id != number


async def test_multiple_matches_keep_contract_without_selecting_an_id(db):
    # The confirmed UNIQUE constraint normally prevents this. The unconstrained
    # test table deliberately exercises the defensive multiple-match contract.
    db[1].connection.execute(db[2]["members"].insert(), {
        "id": UUID(int=99), "member_code": "0007", "full_name": "Test Name", "center_code": "center-a",
    })
    result = await db[0].verify_member(
        external_organization_id="org-a", verification=MemberVerificationInput("0007", "Test Name"),
    )
    assert result.status is Status.MULTIPLE_MATCH
    assert result.external_member_id is None


async def test_member_summary_minimal_projection(db):
    summary = await db[0].get_member_summary(external_organization_id="org-a", external_member_id=str(M1))
    assert summary.external_member_id == str(M1)
    assert summary.display_label == "Test Name"
    assert {field.name for field in fields(summary)} == {"external_member_id", "display_label"}
    sql = str(db[1].statements[-1].compile(dialect=postgresql.dialect()))
    assert "public.members" in sql
    assert "full_name" in sql and "member_code" not in sql


@pytest.mark.parametrize("member_id", [str(M2), str(UUID(int=999)), "0007", "invalid"])
async def test_member_scope_and_uuid_lookup(db, member_id):
    with pytest.raises(ExternalMemberNotFoundError):
        await db[0].get_member_summary(external_organization_id="org-a", external_member_id=member_id)
    with pytest.raises(ExternalMemberNotFoundError):
        await db[0].list_recommended_jobs(external_organization_id="org-a", external_member_id=member_id)


async def test_recommendations_join_flags_and_all_three_scopes(db):
    jobs = await db[0].list_recommended_jobs(external_organization_id="org-a", external_member_id=str(M1))
    assert [job.external_job_id for job in jobs] == [str(J1), str(J4)]
    assert all(isinstance(job, ExternalJobSummary) for job in jobs)
    # The existing gateway contract does not require a published-only filter.
    assert jobs[1].status.value == "closed"
    assert jobs[0].work_location_summary == "Place"
    assert jobs[0].work_schedule_summary == "Schedule"
    assert jobs[0].version == NOW.isoformat()
    assert await db[0].list_recommended_jobs(external_organization_id="org-a", external_member_id=str(M3)) == []


async def test_job_detail_mapping_and_revision(db):
    detail = await db[0].get_job_detail(external_organization_id="org-a", external_job_id=str(J1))
    assert isinstance(detail, ExternalJobDetail)
    assert detail.external_job_id == str(J1)
    assert detail.description == "Description"
    assert detail.work_location == "Place"
    assert detail.work_schedule_text == "Schedule"
    assert detail.version == NOW.isoformat()
    assert detail.updated_at == NOW
    assert detail.application_deadline is None and detail.staff_notes is None
    assert detail.required_conditions == ()
    db[1].connection.execute(db[2]["jobs"].update().where(db[2]["jobs"].c.id == J1).values(updated_at=NOW + timedelta(seconds=1)))
    updated = await db[0].get_job_detail(external_organization_id="org-a", external_job_id=str(J1))
    assert updated.version != detail.version


@pytest.mark.parametrize("job_id", [str(J2), str(UUID(int=999)), "business-job-code"])
async def test_job_scope_and_id_not_business_code(db, job_id):
    with pytest.raises(ExternalJobNotFoundError):
        await db[0].get_job_detail(external_organization_id="org-a", external_job_id=job_id)


def test_revision_is_utc_iso_and_does_not_invent_missing_versions():
    local = NOW.astimezone(timezone(timedelta(hours=9)))
    assert CurrentDbExternalBusinessGateway._revision({"updated_at": local}) == (NOW, NOW.isoformat())
    for value in (None, NOW.replace(tzinfo=None), "not-a-revision"):
        with pytest.raises(ExternalSystemUnavailableError):
            CurrentDbExternalBusinessGateway._revision({"updated_at": value})


async def test_unknown_scope_never_opens_connection(db):
    gateway, engine, _ = db
    calls = [
        gateway.verify_member(external_organization_id="unknown", verification=MemberVerificationInput("0007", "Test Name")),
        gateway.get_member_summary(external_organization_id="unknown", external_member_id=str(M1)),
        gateway.list_recommended_jobs(external_organization_id="unknown", external_member_id=str(M1)),
        gateway.get_job_detail(external_organization_id="unknown", external_job_id=str(J1)),
    ]
    for call in calls:
        with pytest.raises(OrganizationServiceScopeNotConfiguredError):
            await call
    assert engine.statements == []


@pytest.mark.parametrize("mapping", [{}, {"org-a": ""}, {"org-a": " center-a"}, {" org-a": "center-a"}])
def test_configuration_fails_closed(db, mapping):
    with pytest.raises(ExternalBusinessNotConfiguredError):
        CurrentDbExternalBusinessGateway(db[1], mapping)


async def test_database_failure_is_not_no_match_and_has_no_details(db):
    db[1].error = OperationalError("private SQL", {"name": "private-name"}, Exception("private connection"))
    with pytest.raises(ExternalSystemUnavailableError) as failure:
        await db[0].verify_member(external_organization_id="org-a", verification=MemberVerificationInput("0007", "Test Name"))
    assert "private" not in str(failure.value)


def test_complete_port_signatures():
    for name, method in vars(ExternalBusinessGateway).items():
        if inspect.iscoroutinefunction(method):
            implementation = getattr(CurrentDbExternalBusinessGateway, name)
            assert inspect.signature(implementation) == inspect.signature(method)
            assert get_type_hints(implementation) == get_type_hints(method)


async def test_internal_api_resolves_current_db_without_fake(db, monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.state.admin_runtime_settings = SimpleNamespace(
        admin_internal_api_bearer_token=SecretStr("test-incoming"),
        admin_internal_api_scopes={"service-a": "org-a"}, current_db_business_centers={"org-a": "center-a"},
    )
    monkeypatch.setattr(admin_internal_deps, "get_engine", lambda: db[1])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://admin") as client:
        headers = {"Authorization": "Bearer test-incoming"}
        for path, body in [
            ("members:verify", {"member_number": "0007", "name": "Test Name"}),
            ("members:summary", {"external_member_id": str(M1)}),
            ("members:recommended-jobs", {"external_member_id": str(M1)}),
            ("jobs:detail", {"external_job_id": str(J1)}),
        ]:
            response = await client.post("/internal/v1/" + path, headers=headers, json={"service_id": "service-a", **body})
            assert response.status_code == 200, response.text
        db[1].error = OperationalError("private SQL", {}, Exception("private error"))
        response = await client.post("/internal/v1/members:verify", headers=headers, json={"service_id": "service-a", "member_number": "0007", "name": "Test Name"})
        assert response.status_code == 503
        assert response.json() == {"detail": {"error": "external_system_unavailable"}}


@pytest.mark.parametrize("local_integration", [False, True])
async def test_canonical_factory_never_falls_back_to_local_fake(db, monkeypatch, local_integration):
    from pydantic_settings import DotEnvSettingsSource
    monkeypatch.setattr(DotEnvSettingsSource, "_read_env_files", lambda self: {})
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/unused")
    monkeypatch.setenv("APP_ENV", "test")
    from app.core.settings_admin import AdminSettings
    from app.main_admin import create_admin_app
    from app.runtime import admin_local_integration

    # A sentinel would fail if the Internal API still used composition's Fake.
    local_provider = object()
    monkeypatch.setattr(
        admin_local_integration, "build_local_integration_admin_composition",
        lambda **kwargs: SimpleNamespace(application=object(), external_business=local_provider),
    )
    settings = AdminSettings(
        _env_file=None, database_url="postgresql://unused/unused",
        app_env="local" if local_integration else "production",
        admin_internal_api_bearer_token=SecretStr("test-incoming"),
        admin_internal_api_scopes={"service-a": "org-a"},
        current_db_business_centers={"org-a": "center-a"},
        admin_local_integration_mode=local_integration,
        admin_local_integration_scopes={"service-a": "org-a"} if local_integration else {},
    )
    monkeypatch.setattr(admin_internal_deps, "get_engine", lambda: db[1])
    app = create_admin_app(settings)
    assert app.state.admin_internal_business_gateway is None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://admin") as client:
        response = await client.post(
            "/internal/v1/members:verify", headers={"Authorization": "Bearer test-incoming"},
            json={"service_id": "service-a", "member_number": "0007", "name": "Test Name"},
        )
    assert response.status_code == 200
    assert response.json() == {"status": "unique_match", "external_member_id": str(M1)}

import importlib.util
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError

from app.db.admin_staff_provisioning import (
    StaffRegistration, create_admin_staff_tables, register_admin_staff,
)
from app.db.admin_tables import staff_identities, staff_service_permissions
from app.db.staff_identity_repository import SqlAlchemyStaffIdentityRepository


DATA = dict(staff_id="00000000-0000-0000-0000-000000000001",
            identity_provider="https://idp.example.test", external_subject="test-subject",
            service_id="test-service", role="viewer", active=True)


@pytest.fixture
def connection():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        create_admin_staff_tables(conn)
        yield conn
    engine.dispose()


def test_provisioning_scope_repeat_and_preservation(connection):
    register_admin_staff(connection, StaffRegistration(**DATA))
    before = connection.execute(select(staff_identities)).mappings().all()
    assert create_admin_staff_tables(connection) == ("staff_identities", "staff_service_permissions")
    assert set(inspect(connection).get_table_names()) == {"staff_identities", "staff_service_permissions"}
    assert connection.execute(select(staff_identities)).mappings().all() == before


@pytest.mark.parametrize("changes", [
    {"staff_id": "invalid"}, {"identity_provider": ""}, {"external_subject": " "},
    {"service_id": ""}, {"role": "operator"}, {"role": "invalid"}, {"active": "true"},
    {"email": 123}, {"display_name": []}, {"token": "never-accepted"},
    {"identity_provider": "https://accounts.google.com/"},
    {"identity_provider": "https://accounts.google.com//"},
])
def test_invalid_registration_input(changes):
    with pytest.raises(ValidationError):
        StaffRegistration(**{**DATA, **changes})


def test_upsert_permission_and_deactivation(connection):
    register_admin_staff(connection, StaffRegistration(**DATA))
    register_admin_staff(connection, StaffRegistration(**{**DATA, "service_id": "other", "role": "sender"}))
    register_admin_staff(connection, StaffRegistration(**{**DATA, "role": "admin", "active": False}))
    assert connection.execute(select(staff_identities.c.active)).scalar_one() is False
    permissions = connection.execute(select(staff_service_permissions)).mappings().all()
    assert {(p["service_id"], p["role"]) for p in permissions} == {("test-service", "admin"), ("other", "sender")}


def test_duplicate_identity_cannot_rebind(connection):
    register_admin_staff(connection, StaffRegistration(**DATA))
    with pytest.raises(IntegrityError):
        register_admin_staff(connection, StaffRegistration(**{**DATA,
            "staff_id": "00000000-0000-0000-0000-000000000002"}))
    with pytest.raises(ValueError):
        register_admin_staff(connection, StaffRegistration(**{**DATA, "external_subject": "other"}))
    assert len(connection.execute(select(staff_identities)).all()) == 1
    assert len(connection.execute(select(staff_service_permissions)).all()) == 1


def test_permission_failure_rolls_back_identity(connection):
    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO staff_service_permissions"):
            raise RuntimeError("simulated private failure")
    event.listen(connection, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError):
            register_admin_staff(connection, StaffRegistration(**DATA))
    finally:
        event.remove(connection, "before_cursor_execute", fail)
    assert connection.execute(select(staff_identities)).all() == []
    assert connection.execute(select(staff_service_permissions)).all() == []


@pytest.mark.asyncio
async def test_registration_matches_repository_lookup(connection):
    register_admin_staff(connection, StaffRegistration(**DATA))
    class Engine:
        @asynccontextmanager
        async def connect(self):
            yield self

        async def execute(self, statement):
            return connection.execute(statement)
    repo = SqlAlchemyStaffIdentityRepository(Engine())
    identity, permissions = await repo.find_by_oidc_identity(DATA["identity_provider"], DATA["external_subject"])
    assert str(identity.staff_id) == DATA["staff_id"] and identity.active
    assert permissions[0].role.value == "viewer"
    assert await repo.find_by_oidc_identity(DATA["identity_provider"] + "/", DATA["external_subject"]) is None

    from app.adapter.oidc_staff_auth import OidcStaffAuthenticator
    class Validator:
        async def validate(self, token):
            return {"iss": DATA["identity_provider"], "sub": DATA["external_subject"]}
    auth = OidcStaffAuthenticator(token="offline", requested_service_id=DATA["service_id"],
        validator=Validator(), repository=repo)
    staff = await auth.get_current_staff()
    assert str(staff.staff_id) == DATA["staff_id"]


@pytest.mark.parametrize("payload", [
    {"token": "private-input"},
    {**DATA, "identity_provider": "https://accounts.google.com/"},
])
def test_cli_rejects_input_without_loading_settings_or_echoing(monkeypatch, capsys, payload):
    path = Path(__file__).resolve().parents[1] / "scripts/register_admin_staff.py"
    spec = importlib.util.spec_from_file_location("staff_registration_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    async def forbidden(_):
        calls.append(True)
    monkeypatch.setattr(module, "register", forbidden)
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(payload)))
    assert module.main() == 1
    assert calls == []
    output = capsys.readouterr()
    assert output.err == "Staff registration failed.\n" and output.out == ""


@pytest.mark.asyncio
async def test_no_permission_is_denied_with_persisted_identity(connection):
    from app.adapter.oidc_staff_auth import OidcStaffAuthenticator
    from app.domain.errors.errors import StaffServiceScopeError

    register_admin_staff(connection, StaffRegistration(**DATA))
    connection.execute(staff_service_permissions.delete())
    class Engine:
        @asynccontextmanager
        async def connect(self):
            yield self

        async def execute(self, statement):
            return connection.execute(statement)
    class Validator:
        async def validate(self, token):
            return {"iss": DATA["identity_provider"], "sub": DATA["external_subject"]}
    for requested in (None, DATA["service_id"]):
        auth = OidcStaffAuthenticator(token="offline", requested_service_id=requested,
            validator=Validator(), repository=SqlAlchemyStaffIdentityRepository(Engine()))
        with pytest.raises(StaffServiceScopeError):
            await auth.get_current_staff()


@pytest.mark.parametrize("fails", [False, True])
def test_registration_cli_safe_result(monkeypatch, capsys, fails):
    path = Path(__file__).resolve().parents[1] / "scripts/register_admin_staff.py"
    spec = importlib.util.spec_from_file_location("staff_registration_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    async def manual(registration):
        calls.append(registration)
        if fails:
            raise RuntimeError("private database details")
    monkeypatch.setattr(module, "register", manual)
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(StaffRegistration(**DATA).model_dump_json()))
    assert module.main() == (1 if fails else 0)
    assert len(calls) == 1
    output = capsys.readouterr()
    assert "private" not in output.err and DATA["external_subject"] not in output.out

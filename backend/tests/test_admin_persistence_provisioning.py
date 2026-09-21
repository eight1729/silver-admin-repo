from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Table, create_engine, inspect
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.app_factory import configure_shared_infrastructure
from app.db.admin_notification_provisioning import (
    ADMIN_NOTIFICATION_TABLES,
    create_admin_notification_tables,
)


EXPECTED_TABLES = (
    "admin_notification_operations",
    "admin_notification_targets",
    "admin_notification_deliveries",
    "admin_notification_audit_events",
    "admin_notification_outbox",
)


def test_fresh_provisioning_is_repeatable_and_scoped():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            assert create_admin_notification_tables(conn) == EXPECTED_TABLES
            assert create_admin_notification_tables(conn) == EXPECTED_TABLES
            assert set(inspect(conn).get_table_names()) == set(EXPECTED_TABLES)
            for table in ADMIN_NOTIFICATION_TABLES:
                assert {c["name"] for c in inspect(conn).get_columns(table.name)} == set(table.c.keys())
    finally:
        engine.dispose()


@pytest.mark.parametrize("existing", [(), ("lease_expires_at",), ("claim_token",),
                                      ("lease_expires_at", "claim_token")])
def test_provisioning_upgrades_partial_legacy_outbox_without_reset(existing):
    engine = create_engine("sqlite://")
    definitions = {"lease_expires_at": "DATETIME", "claim_token": "TEXT"}
    try:
        with engine.begin() as conn:
            extra = "".join(f", {name} {definitions[name]}" for name in existing)
            conn.exec_driver_sql("CREATE TABLE admin_notification_outbox "
                "(command_id TEXT, idempotency_key TEXT, message_note TEXT, state TEXT" + extra + ")")
            conn.exec_driver_sql("INSERT INTO admin_notification_outbox "
                "(command_id, idempotency_key, message_note, state) VALUES ('command', 'key', 'body', 'delivering')")
            for name in existing:
                value = "2026-01-01 00:00:00" if name == "lease_expires_at" else "existing-token"
                conn.exec_driver_sql(f"UPDATE admin_notification_outbox SET {name} = ?", (value,))
            before = dict(conn.exec_driver_sql("SELECT * FROM admin_notification_outbox").mappings().one())
            create_admin_notification_tables(conn)
            create_admin_notification_tables(conn)
            after = dict(conn.exec_driver_sql("SELECT * FROM admin_notification_outbox").mappings().one())
            assert {k: after[k] for k in before} == before
            assert all(after[name] is None for name in definitions if name not in existing)
            columns = {c["name"]: c for c in inspect(conn).get_columns("admin_notification_outbox")}
            assert all(columns[name]["nullable"] for name in definitions)
    finally:
        engine.dispose()


def _error_app(error: Exception) -> FastAPI:
    app = FastAPI()
    configure_shared_infrastructure(app, "")

    @app.get("/failure")
    async def failure():
        raise error

    return app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status", "body"),
    [
        (
            OperationalError("statement", {}, Exception("unavailable")),
            503,
            {"detail": {"error": "database_unavailable"}},
        ),
        (
            SQLAlchemyError("failure"),
            500,
            {"detail": {"error": "internal_error"}},
        ),
    ],
)
async def test_shared_db_exception_handlers_return_safe_json(error, status, body):
    transport = httpx.ASGITransport(app=_error_app(error), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/failure")
    assert response.status_code == status
    assert response.json() == body


def test_admin_provisioning_is_exact_ordered_and_checkfirst(monkeypatch):
    calls = []

    def record_create(self, connection, *, checkfirst=False):
        calls.append((self.name, connection, checkfirst))

    monkeypatch.setattr(Table, "create", record_create)
    monkeypatch.setattr("app.db.admin_notification_provisioning.migrate_admin_outbox_recovery", lambda connection: None)
    connection = object()
    names = create_admin_notification_tables(connection)
    assert names == EXPECTED_TABLES
    assert tuple(table.name for table in ADMIN_NOTIFICATION_TABLES) == EXPECTED_TABLES
    assert calls == [(name, connection, True) for name in EXPECTED_TABLES]


def test_admin_provisioning_has_only_internal_foreign_keys_and_no_schema():
    names = set(EXPECTED_TABLES)
    for table in ADMIN_NOTIFICATION_TABLES:
        assert table.schema is None
        assert all(foreign_key.column.table.name in names for foreign_key in table.foreign_keys)


def test_manual_script_uses_scoped_create_without_seed_or_whole_metadata():
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "provision_admin_notification_tables.py").read_text(
        encoding="utf-8"
    )
    assert "create_admin_notification_tables" in source
    assert "WindowsSelectorEventLoopPolicy" in source
    assert "metadata.create_all" not in source
    assert "create_and_seed" not in source
    assert "seed" not in source.lower()

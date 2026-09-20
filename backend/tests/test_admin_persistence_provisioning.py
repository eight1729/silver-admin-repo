from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Table
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

"""Explicit one-time provisioning scope for Admin notification persistence."""

from sqlalchemy.engine import Connection
from sqlalchemy import inspect, text

from app.db.admin_tables import (
    admin_notification_audit_events,
    admin_notification_deliveries,
    admin_notification_operations,
    admin_notification_outbox,
    admin_notification_targets,
)


ADMIN_NOTIFICATION_TABLES = (
    admin_notification_operations,
    admin_notification_targets,
    admin_notification_deliveries,
    admin_notification_audit_events,
    admin_notification_outbox,
)


def create_admin_notification_tables(connection: Connection) -> tuple[str, ...]:
    """Create only the five Admin notification tables, in FK-safe order."""
    for table in ADMIN_NOTIFICATION_TABLES:
        table.create(connection, checkfirst=True)
    migrate_admin_outbox_recovery(connection)
    return tuple(table.name for table in ADMIN_NOTIFICATION_TABLES)


def migrate_admin_outbox_recovery(connection: Connection) -> None:
    """Add nullable lease fencing metadata; legacy delivering rows are reclaimable.

    Run with old workers stopped. Never regenerate command IDs or payloads.
    """
    columns = {c["name"] for c in inspect(connection).get_columns("admin_notification_outbox")}
    timestamp = "TIMESTAMP WITH TIME ZONE" if connection.dialect.name == "postgresql" else "DATETIME"
    for name, sql_type in (("lease_expires_at", timestamp), ("claim_token", "TEXT")):
        if name not in columns:
            connection.execute(text(f"ALTER TABLE admin_notification_outbox ADD COLUMN {name} {sql_type} NULL"))

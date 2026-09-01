"""Explicit one-time provisioning scope for Admin notification persistence."""

from sqlalchemy.engine import Connection

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
    return tuple(table.name for table in ADMIN_NOTIFICATION_TABLES)

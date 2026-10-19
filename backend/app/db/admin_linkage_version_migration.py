"""Admin-owned feature DB only; do not backfill historical notification intent."""
from sqlalchemy import inspect


def migrate_admin_linkage_version(connection):
    columns = {c['name'] for c in inspect(connection).get_columns('admin_notification_outbox')}
    if 'linkage_version' not in columns:
        connection.exec_driver_sql('ALTER TABLE admin_notification_outbox ADD COLUMN linkage_version TEXT NULL')

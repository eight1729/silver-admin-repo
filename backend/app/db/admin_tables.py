"""Admin-owned SQLAlchemy table metadata for repository-local persistence."""

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, MetaData,
    Table, Text, UniqueConstraint,
)

metadata = MetaData()

admin_notification_operations = Table(
    "admin_notification_operations", metadata,
    Column("operation_id", Text, primary_key=True),
    Column("service_id", Text, nullable=False),
    Column("job_id", Text, nullable=False),
    Column("job_version", Text),
    Column("notification_type", Text, nullable=False),
    Column("message_greeting", Text, nullable=False),
    Column("message_introduction", Text, nullable=False),
    Column("message_note", Text, nullable=False),
    Column("message_version", Integer, nullable=False),
    Column("message_hash", Text, nullable=False),
    Column("validation_snapshot", JSON),
    Column("status", Text, nullable=False),
    Column("created_by_staff_id", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("validated_at", DateTime(timezone=True)),
    Column("send_requested_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Index("idx_admin_operations_service_created", "service_id", "created_at"),
)

admin_notification_targets = Table(
    "admin_notification_targets", metadata,
    Column("operation_id", Text, ForeignKey("admin_notification_operations.operation_id", ondelete="CASCADE"), primary_key=True),
    Column("member_id", Text, primary_key=True),
    Column("selected", Boolean, nullable=False),
    Column("line_linked", Boolean, nullable=False),
    Column("eligibility", Text),
    Column("reason", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

admin_notification_deliveries = Table(
    "admin_notification_deliveries", metadata,
    Column("delivery_id", Text, primary_key=True),
    Column("operation_id", Text, ForeignKey("admin_notification_operations.operation_id", ondelete="CASCADE"), nullable=False),
    Column("member_id", Text, nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("request_id", Text),
    Column("error_code", Text),
    Column("error_message", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("sent_at", DateTime(timezone=True)),
    Index("idx_admin_deliveries_operation_created", "operation_id", "created_at"),
)

admin_notification_audit_events = Table(
    "admin_notification_audit_events", metadata,
    Column("audit_id", Text, primary_key=True),
    Column("operation_id", Text, ForeignKey("admin_notification_operations.operation_id", ondelete="CASCADE"), nullable=False),
    Column("event_type", Text, nullable=False),
    Column("staff_id", Text),
    Column("details", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("idx_admin_audit_operation_created", "operation_id", "created_at"),
)

admin_notification_outbox = Table(
    "admin_notification_outbox", metadata,
    Column("outbox_id", Text, primary_key=True),
    Column("command_id", Text, nullable=False, unique=True),
    Column("operation_id", Text, ForeignKey("admin_notification_operations.operation_id", ondelete="CASCADE"), nullable=False),
    Column("target_id", Text, nullable=False),
    Column("organization_id", Text, nullable=False),
    Column("service_id", Text, nullable=False),
    Column("external_member_id", Text, nullable=False),
    Column("job_id", Text, nullable=False),
    Column("job_version", Text, nullable=False),
    Column("message_greeting", Text, nullable=False),
    Column("message_introduction", Text, nullable=False),
    Column("message_note", Text, nullable=False),
    Column("message_version", Integer, nullable=False),
    Column("message_hash", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False, unique=True),
    Column("correlation_id", Text, nullable=False),
    Column("requested_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("state", Text, nullable=False),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("claim_token", Text),
    UniqueConstraint("operation_id", "target_id", name="uq_admin_outbox_operation_target"),
    Index("idx_admin_outbox_state_created", "state", "created_at"),
)

staff_identities = Table(
    "staff_identities", metadata,
    Column("staff_id", Text, primary_key=True),
    Column("identity_provider", Text, nullable=False),
    Column("external_subject", Text, nullable=False),
    Column("email", Text),
    Column("display_name", Text),
    Column("active", Boolean, nullable=False, server_default="true"),
    UniqueConstraint("identity_provider", "external_subject", name="uq_staff_oidc_identity"),
)

staff_service_permissions = Table(
    "staff_service_permissions", metadata,
    Column("staff_id", Text, ForeignKey("staff_identities.staff_id", ondelete="CASCADE"), primary_key=True),
    Column("service_id", Text, primary_key=True),
    Column("role", Text, nullable=False),
    Index("idx_staff_permissions_service", "service_id"),
)

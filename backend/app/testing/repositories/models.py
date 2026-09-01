"""Compatibility re-exports for the test adapter."""

from app.domain.models.admin_notification import (
    AuditScalar,
    AuditValue,
    NotificationAuditEvent,
    NotificationDeliveryRecord,
    NotificationMessage,
    NotificationOperationRecord,
    NotificationTargetRecord,
)

__all__ = [
    "AuditScalar",
    "AuditValue",
    "NotificationAuditEvent",
    "NotificationDeliveryRecord",
    "NotificationMessage",
    "NotificationOperationRecord",
    "NotificationTargetRecord",
]

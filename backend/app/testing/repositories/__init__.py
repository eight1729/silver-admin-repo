"""Public imports for the local-demo notification repository."""

from app.testing.repositories.errors import (
    AuditEventAlreadyExistsError,
    DeliveryAlreadyExistsError,
    DeliveryNotFoundError,
    NotificationRepositoryError,
    OperationAlreadyExistsError,
    OperationNotFoundError,
    RepositoryStateError,
    SendAttemptAlreadyExistsError,
    ServiceScopeViolationError,
)
from app.testing.repositories.in_memory_notification_repository import (
    InMemoryNotificationRepository,
)
from app.testing.repositories.async_in_memory_notification_repository import (
    AsyncInMemoryNotificationRepository,
)
from app.testing.repositories.models import (
    NotificationAuditEvent,
    NotificationDeliveryRecord,
    NotificationMessage,
    NotificationOperationRecord,
    NotificationTargetRecord,
)

__all__ = [
    "AuditEventAlreadyExistsError",
    "DeliveryAlreadyExistsError",
    "DeliveryNotFoundError",
    "InMemoryNotificationRepository",
    "AsyncInMemoryNotificationRepository",
    "NotificationAuditEvent",
    "NotificationDeliveryRecord",
    "NotificationMessage",
    "NotificationOperationRecord",
    "NotificationRepositoryError",
    "NotificationTargetRecord",
    "OperationAlreadyExistsError",
    "OperationNotFoundError",
    "RepositoryStateError",
    "SendAttemptAlreadyExistsError",
    "ServiceScopeViolationError",
]

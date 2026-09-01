"""Implementation-independent Admin notification repository errors."""


class NotificationRepositoryError(Exception):
    pass


class OperationNotFoundError(NotificationRepositoryError):
    pass


class OperationAlreadyExistsError(NotificationRepositoryError):
    pass


class DeliveryNotFoundError(NotificationRepositoryError):
    pass


class DeliveryAlreadyExistsError(NotificationRepositoryError):
    pass


class SendAttemptAlreadyExistsError(NotificationRepositoryError):
    pass


class AuditEventAlreadyExistsError(NotificationRepositoryError):
    pass


class ServiceScopeViolationError(NotificationRepositoryError):
    pass


class RepositoryStateError(NotificationRepositoryError):
    pass

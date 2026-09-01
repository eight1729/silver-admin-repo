from typing import Protocol
from uuid import UUID

from app.domain.models.notification import QueueEnqueueResult


class QueueGateway(Protocol):
    """通知オペレーションのエンキュー契約。

    - エンキュー粒度は operation 単位
    - operation_id は UUID
    - request_id はトレース用（LINE API の冪等キーではない）
    - service_id は引数に含めない
    - Cloud Tasks 固有型を含めない
    """

    async def enqueue_notification_operation(
        self,
        *,
        operation_id: UUID,
        request_id: str,
    ) -> QueueEnqueueResult: ...


class ScopedQueueGateway(Protocol):
    """Optional capability that preserves the selected Admin service scope."""

    async def enqueue_scoped_notification_operation(
        self,
        *,
        service_id: str,
        operation_id: UUID,
        request_id: str,
    ) -> QueueEnqueueResult: ...

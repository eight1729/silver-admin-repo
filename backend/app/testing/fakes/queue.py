"""Fake implementation of QueueGateway for use in tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import UUID

from app.domain.errors.errors import QueueError
from app.domain.models.notification import QueueEnqueueResult


@dataclass
class _Call:
    method: str
    kwargs: dict[str, Any]


class FakeQueueGateway:
    """Test double for QueueGateway.

    Supports two modes:

    - ``record_only`` (default): records every enqueue call and returns a
      deterministic QueueEnqueueResult. The handler is never invoked.
    - ``inline``: records the call, then synchronously awaits a registered
      async handler before returning the result. This lets tests drive
      process_operation from inside send_operation without threads or
      background tasks.

    In inline mode the handler **must** be registered via
    ``register_handler()`` before the first enqueue call. If no handler is
    registered a ``QueueError`` is raised.

    Set ``raise_on_next`` to an exception instance to simulate an enqueue
    failure for the next call (cleared automatically after raising, before
    the handler would be invoked).

    Usage (record_only)::

        fake = FakeQueueGateway()
        result = await fake.enqueue_notification_operation(
            operation_id=some_uuid,
            request_id="req-001",
        )
        assert result.task_name == f"notification-operation-{some_uuid}"
        assert fake.calls[0].kwargs["operation_id"] == some_uuid

    Usage (inline)::

        fake = FakeQueueGateway(mode="inline")

        async def handler(*, operation_id: UUID, request_id: str) -> None:
            await service.process_operation(...)

        fake.register_handler(handler)
        await service.send_operation(...)  # process runs inline
    """

    def __init__(self, *, mode: str = "record_only") -> None:
        if mode not in ("record_only", "inline"):
            raise ValueError(f"mode must be 'record_only' or 'inline', got {mode!r}")
        self.calls: list[_Call] = []
        # Raise-on-next: set to an exception instance to raise it once, then clear.
        # The handler is NOT called when raise_on_next is consumed.
        self.raise_on_next: BaseException | None = None
        # If set, use this fixed datetime as enqueued_at instead of datetime.now()
        self.fixed_enqueued_at: datetime | None = None
        self._mode = mode
        self._handler: Callable[..., Awaitable[None]] | None = None

    @property
    def mode(self) -> str:
        return self._mode

    def register_handler(self, handler: Callable[..., Awaitable[None]]) -> None:
        """Register the async handler called synchronously in inline mode.

        The handler signature must be::

            async def handler(*, operation_id: UUID, request_id: str) -> None: ...
        """
        self._handler = handler

    async def enqueue_notification_operation(
        self,
        *,
        operation_id: UUID,
        request_id: str,
    ) -> QueueEnqueueResult:
        return await self._enqueue(
            service_id=None, operation_id=operation_id, request_id=request_id
        )

    async def enqueue_scoped_notification_operation(
        self,
        *,
        service_id: str,
        operation_id: UUID,
        request_id: str,
    ) -> QueueEnqueueResult:
        if not service_id or service_id != service_id.strip():
            raise QueueError("service scope is required for scoped enqueue")
        return await self._enqueue(
            service_id=service_id,
            operation_id=operation_id,
            request_id=request_id,
        )

    async def _enqueue(self, *, service_id, operation_id, request_id):
        kwargs = {"operation_id": operation_id, "request_id": request_id}
        if service_id is not None:
            kwargs["service_id"] = service_id
        self.calls.append(
            _Call(
                method=(
                    "enqueue_scoped_notification_operation"
                    if service_id is not None
                    else "enqueue_notification_operation"
                ),
                kwargs=kwargs,
            )
        )

        if self.raise_on_next is not None:
            exc = self.raise_on_next
            self.raise_on_next = None
            raise exc

        enqueued_at = (
            self.fixed_enqueued_at
            if self.fixed_enqueued_at is not None
            else datetime.now(tz=timezone.utc)
        )
        result = QueueEnqueueResult(
            task_name=f"notification-operation-{operation_id}",
            enqueued_at=enqueued_at,
        )

        if self._mode == "inline":
            if self._handler is None:
                raise QueueError(
                    "FakeQueueGateway is in inline mode but no handler has been "
                    "registered; call register_handler() before enqueueing"
                )
            if service_id is None:
                await self._handler(operation_id=operation_id, request_id=request_id)
            else:
                await self._handler(
                    service_id=service_id,
                    operation_id=operation_id,
                    request_id=request_id,
                )

        return result

    def reset(self) -> None:
        """Clear call history, raise_on_next, and fixed_enqueued_at.

        Note: ``mode`` and the registered handler are intentionally preserved
        so that the same Fake can be reused across reset cycles without
        re-configuration.
        """
        self.calls.clear()
        self.raise_on_next = None
        self.fixed_enqueued_at = None

"""Bounded Admin notification dispatch and reconciliation runner."""

import asyncio
import logging
from collections.abc import Iterable

from app.domain.enums.enums import OperationStatus

logger = logging.getLogger(__name__)


class AdminNotificationRunner:
    """Drive persisted notification operations without frontend side effects."""

    def __init__(self, *, repository, dispatcher, reconciler, service_ids: Iterable[str], interval_seconds: float = 5.0) -> None:
        self._repository = repository
        self._dispatcher = dispatcher
        self._reconciler = reconciler
        self._service_ids = tuple(service_ids)
        self._interval = interval_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._cursors = {}

    async def run_cycle(self) -> None:
        for service_id in self._service_ids:
            try:
                operations = await self._repository.list_recovery_operations(
                    service_id, after=self._cursors.get(service_id), limit=50)
            except Exception as error:
                logger.warning("Admin recovery selection failed: %s", type(error).__name__)
                continue
            self._cursors[service_id] = operations[-1].operation_id if operations else None
            for operation in operations:
                if operation.status is not OperationStatus.CANCELLED:
                    for action in (self._dispatcher.dispatch_operation, self._reconciler.reconcile_operation):
                        try:
                            await action(service_id=service_id, operation_id=operation.operation_id)
                        except Exception as error:
                            # Submission failure must not block existing result polling.
                            logger.warning("Admin notification operation failed: %s", type(error).__name__)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="admin-notification-runner")

    async def stop(self) -> None:
        self._stop.set()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # A single cycle failure must not permanently stop later work.
                logger.warning("Admin notification cycle failed: %s", type(error).__name__)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                continue

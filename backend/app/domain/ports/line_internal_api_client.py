from typing import Any, Protocol
from uuid import UUID


class LineInternalApiClient(Protocol):
    async def submit_notification_command(
        self, command: Any
    ) -> Any: ...

    async def get_notification_result(self, command_id: UUID) -> Any: ...

    async def batch_get_linkages(
        self, request: Any
    ) -> Any: ...

    async def resolve_deep_link(
        self, request: Any
    ) -> Any: ...

    async def check_staging_send_readiness(
        self, request: Any
    ) -> Any: ...

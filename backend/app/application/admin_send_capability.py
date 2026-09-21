"""LINE-owned capability, consumed for metadata and fresh reservation guards."""

from app.contracts.admin_line_internal_v1 import SendCapabilityRequest, SendCapabilityResponse
from app.application.notification_service import OperationNotSendableError


async def fetch_send_capability(client, scope):
    result = await client.check_send_capability(SendCapabilityRequest(scope=scope))
    # Validate also at the application boundary (including injected clients).
    return SendCapabilityResponse.model_validate(result)


class AdminSendCapabilityGuard:
    def __init__(self, *, client, scope_resolver):
        self.client = client
        self.scope_resolver = scope_resolver

    async def __call__(self, service_id: str, sendable_count: int) -> None:
        try:
            capability = await fetch_send_capability(self.client, self.scope_resolver.resolve(service_id))
        except Exception:
            raise OperationNotSendableError("line_capability_unavailable") from None
        if (capability.mode == "disabled" or not capability.live_send_enabled
                or not capability.ready or capability.blocking_reasons):
            raise OperationNotSendableError("line_send_not_ready")
        if capability.max_recipients is not None and sendable_count > capability.max_recipients:
            raise OperationNotSendableError("line_recipient_limit_exceeded")

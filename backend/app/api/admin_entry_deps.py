"""Admin entrypoint dependency without importing legacy LINE implementations."""

from fastapi import HTTPException


def get_admin_application_service():
    raise HTTPException(status_code=503, detail={"error": "service_unavailable"})


def get_admin_line_send_mode():
    return {
        "mode": "unavailable",
        "max_recipients": None,
        "message_prefix": None,
        "live_send_enabled": False,
        "ready": False,
        "blocking_reasons": ("line_capability_unavailable",),
    }


async def get_admin_line_send_mode_for_runtime(
    runtime_settings=None, *, integration=None, service_id: str | None = None
):
    if runtime_settings is None:
        from app.core.settings_admin import admin_settings

        runtime_settings = admin_settings

    if integration is None or service_id is None:
        return get_admin_line_send_mode()
    try:
        from app.application.admin_send_capability import fetch_send_capability

        capability = await fetch_send_capability(
            integration.boundary.client, integration.scope_resolver.resolve(service_id)
        )
    except Exception:
        return get_admin_line_send_mode()
    result = capability.model_dump()
    result["ready"] = capability.ready and capability.live_send_enabled and not capability.blocking_reasons and capability.mode != "disabled"
    return result

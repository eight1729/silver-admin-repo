"""Admin entrypoint dependency without importing legacy LINE implementations."""

from fastapi import HTTPException


def get_admin_application_service():
    raise HTTPException(status_code=503, detail={"error": "service_unavailable"})


def get_admin_line_send_mode():
    return {
        "mode": "fake",
        "max_recipients": None,
        "message_prefix": None,
        "live_send_enabled": False,
        "ready": False,
        "blocking_reasons": ("line_readiness_unavailable",),
    }


async def get_admin_line_send_mode_for_runtime(
    runtime_settings=None, *, integration=None, service_id: str | None = None
):
    if runtime_settings is None:
        from app.core.settings_admin import admin_settings

        runtime_settings = admin_settings

    if runtime_settings.admin_local_integration_mode:
        unavailable = {
            "mode": "staging_live",
            "max_recipients": None,
            "message_prefix": None,
            "live_send_enabled": False,
            "ready": False,
            "blocking_reasons": ("line_readiness_unavailable",),
        }
        if integration is None or service_id is None:
            return unavailable
        try:
            from app.contracts.admin_line_internal_v1 import StagingSendReadinessRequest

            scope = integration.scope_resolver.resolve(service_id)
            readiness = await integration.boundary.client.check_staging_send_readiness(
                StagingSendReadinessRequest(scope=scope)
            )
        except Exception:
            return unavailable
        return {
            "mode": "staging_live",
            "max_recipients": readiness.max_recipients,
            "message_prefix": readiness.message_prefix,
            "live_send_enabled": readiness.live_send_enabled,
            "ready": readiness.ready,
            "blocking_reasons": readiness.blocking_reasons,
        }
    return get_admin_line_send_mode()

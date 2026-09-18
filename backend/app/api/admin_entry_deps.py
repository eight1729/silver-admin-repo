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


def line_send_is_live(runtime_settings) -> bool:
    """Admin から LINE へ実際に command が飛ぶ構成か。

    ★ここが False のときだけ画面に「Fake」と名乗ってよい。
      現行は local integration のときだけ LINE 側に問い合わせ、それ以外は `fake` 固定を
      返していた。本番 composition を入れると、**画面は「Fake／実 LINE 送信は行いません」
      と出るのに outbox → dispatcher → LINE Internal API へ command が実際に飛ぶ**。
      職員が「これは練習」と思って送信を押す事故になるので、構成を見て判定する。
    """
    if runtime_settings.admin_local_integration_mode:
        return True
    base_url = getattr(runtime_settings, "admin_external_business_base_url", None)
    return bool(
        runtime_settings.app_env.strip().lower() in {"staging", "production"}
        and base_url
        and base_url.strip()
    )


async def get_admin_line_send_mode_for_runtime(
    runtime_settings=None, *, integration=None, service_id: str | None = None
):
    """LINE 側の readiness をそのまま画面へ返す。届かなければ fail-closed。

    `integration` は composition（`boundary.client` と `scope_resolver` を持つもの）。
    local integration と本番のどちらの合成でも同じ口で扱える。
    """
    if runtime_settings is None:
        from app.core.settings_admin import admin_settings

        runtime_settings = admin_settings

    if line_send_is_live(runtime_settings):
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

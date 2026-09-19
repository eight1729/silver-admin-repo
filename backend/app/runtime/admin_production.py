"""staging / production 向けの Admin 合成（ic を外部業務システムとして繋ぐ）。

`admin_local_integration.py` が local 向けに `build_production_admin_application` を
呼んでいるのと同じことを、**ic の HTTP アダプタ**と設定から組み立てて行う。
ここが無いと `get_admin_application_service` が 503 を返すだけで、画面が動かない。

送信キューは POC では `LocalInlineNotificationQueue`（送信ボタンの要求の中で LINE へ投げる）。
対象 100 名以下・Cloud Run の timeout 300s で足りる。本番の非同期キューは別計画。
"""

from dataclasses import dataclass

from app.adapter.admin_scope import ConfiguredOrganizationServiceScopeResolver
from app.adapter.external_business_http import HttpExternalBusinessGateway
from app.adapter.local_inline_notification_queue import LocalInlineNotificationQueue
from app.application.admin_service import AdminApplicationService
from app.core.settings_admin import AdminSettings
from app.runtime.admin_line import AdminLineRuntime, build_production_admin_application


@dataclass(frozen=True)
class ProductionAdminComposition:
    """`LocalIntegrationAdminComposition` と同じ形にしておく。

    送信モードの問い合わせ（`get_admin_line_send_mode_for_runtime`）は
    `boundary.client` と `scope_resolver` しか見ないので、どちらの合成でも同じ口で扱える。
    """

    application: AdminApplicationService
    boundary: AdminLineRuntime
    queue: object
    external_business: object
    dispatch: object
    scope_resolver: object


def build_production_admin_composition(
    *,
    runtime_settings: AdminSettings,
    engine=None,
    client=None,
    external_business=None,
    queue=None,
) -> ProductionAdminComposition:
    environment = runtime_settings.app_env.strip().lower()
    if environment not in {"staging", "production"}:
        raise RuntimeError(
            "Admin production composition requires APP_ENV=staging or production"
        )
    if not runtime_settings.admin_external_business_scopes:
        raise RuntimeError("Admin production composition requires configured scopes")

    scope_resolver = ConfiguredOrganizationServiceScopeResolver(
        runtime_settings.admin_external_business_scopes
    )

    if external_business is None:
        from app.services.http_client import get_client

        external_business = HttpExternalBusinessGateway(
            client=client if client is not None else get_client(),
            base_url=runtime_settings.admin_external_business_base_url,
            environment=environment,
        )
    if queue is None:
        queue = LocalInlineNotificationQueue()

    application, boundary, dispatch = build_production_admin_application(
        external_business_gateway=external_business,
        queue_gateway=queue,
        scope_resolver=scope_resolver,
        engine=engine,
        client=client,
        runtime_settings=runtime_settings,
    )
    return ProductionAdminComposition(
        application=application,
        boundary=boundary,
        queue=queue,
        external_business=external_business,
        dispatch=dispatch,
        scope_resolver=scope_resolver,
    )

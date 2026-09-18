"""入口の鍵 — `/health` 以外の全経路に共有 Bearer を必須化する。

なぜ要るか
----------
`APP_ENV=staging` では `get_staff_authenticator_http` が `DemoStaffAuthenticator` を返し、
**全リクエストが認証なしの Admin ロール**になる（`app/api/admin_auth.py`）。
つまり URL を知っていれば誰でも作成・対象選択・送信が打て、`POST /admin/demo/reset` は
台帳を丸ごと消す。staging は関係者が閲覧できる環境なので、このままでは置けない。

これは「認証」ではない
----------------------
**誰が操作したかは記録されない。**Demo 系のままである。これは入口に鍵を1つ掛けるだけで、
staging を成立させるための最小の措置。職員の識別は production の OIDC で行う。

通す経路（3 つだけ）
--------------------
- `GET /health` … 死活監視。Cloud Run が叩く
- `POST /internal/v1/members:verify` … LINE 窓口から来る。**別のトークン**で照合する
- `POST /internal/v1/reconcile:run` … Cloud Scheduler から来る。**Google OIDC** で照合する
  （static Bearer も要求すると、Scheduler は永久に 401 になる）

設定が無ければ何もしない。local / test の既存の動きを変えないため。
"""

import hmac

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.settings_admin import AdminSettings

# static Bearer を要求しない経路。**それぞれ別の方法で守られている**
EXEMPT_PATHS = frozenset({
    "/health",
    "/internal/v1/members:verify",
    "/internal/v1/reconcile:run",
})


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def needs_guard(runtime_settings: AdminSettings) -> bool:
    """職員の経路が「認証なしの Admin ロール」で外に出てしまう構成か。

    `get_staff_authenticator_http` は local / development / demo / staging / test を
    すべて `DemoStaffAuthenticator` で通す。このうち**外に出るのは staging**（と production だが
    そちらは OIDC が入る）。したがって staging では鍵を必須にする。
    """
    return runtime_settings.app_env.strip().lower() in {"staging", "production"}


def install_static_bearer_guard(app: FastAPI, runtime_settings: AdminSettings) -> None:
    secret = runtime_settings.admin_static_bearer_token
    if secret is None or not secret.get_secret_value().strip():
        # ★設定漏れで黙って無認証にしない。**起動を止める。**
        #   起動できてしまうと、誰も気づかないまま台帳を開いた状態で運用が始まる。
        #   （local / development / demo / test は今までどおり素通し）
        if needs_guard(runtime_settings):
            raise RuntimeError(
                "ADMIN_STATIC_BEARER_TOKEN is required when APP_ENV is staging or "
                "production: staff requests would otherwise be unauthenticated"
            )
        return
    expected = secret.get_secret_value()

    @app.middleware("http")
    async def require_static_bearer(request: Request, call_next):
        # CORS の事前確認には Authorization が付かない。ここで弾くと画面が動かない
        if request.method == "OPTIONS" or request.url.path in EXEMPT_PATHS:
            return await call_next(request)
        token = _bearer(request)
        # ★compare_digest で比べる（長さの違いだけでも早期に返さない）
        if token is None or not hmac.compare_digest(token, expected):
            return JSONResponse(
                status_code=401, content={"detail": {"error": "authorization_required"}}
            )
        return await call_next(request)

"""Admin が外から受ける 2 本（職員の画面経路ではない）。

    POST /internal/v1/members:verify   LINE 窓口 → Admin（初回連携の本人照合）
    POST /internal/v1/reconcile:run    Cloud Scheduler → Admin（配信結果の突き合わせ）

どちらも `/admin/*` とは別の認証で守る。static Bearer（職員の入口の鍵）の対象外で、
`app/api/static_bearer.py:EXEMPT_PATHS` に入れてある。

## 本人照合

仕様書 §2 のとおり、現行は **LINE → Admin の HTTP 境界が存在しない**。初回連携で
「会員番号＋氏名」を照合する口が port にも無いので、ここで 1 本新設して ic に中継する。

**氏名は保存もログ出力もしない。**入力（氏名）は LINE →Admin→ic と流れ、`display_label` が
逆向きに戻るだけで、Admin は本文をログに書かない。ic 側は不一致の理由を `not_matched` の
1 種類に畳んで返す（存在確認への対策）ので、こちらでも理由を出し分けない。

## reconcile

Reconciler を起動する caller が現行には無い（仕様書 §14）。Google OIDC の audience と
呼び出し元 SA の**両方**を検証する。どちらの設定が欠けても全拒否（fail-closed）。
"""

import asyncio
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.admin_auth import get_admin_runtime_settings
from app.core.settings_admin import AdminSettings
from app.domain.enums.enums import OperationStatus
from app.domain.errors.errors import (
    ExternalMemberNotFoundError,
    ExternalSystemUnavailableError,
)
from app.domain.ports.organization_service_scope import (
    OrganizationServiceScopeNotConfiguredError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/v1", tags=["internal"])


class MemberVerifyRequest(BaseModel):
    service_id: str = Field(min_length=1, max_length=128)
    member_number: str = Field(min_length=1, max_length=64)
    full_name: str = Field(min_length=1, max_length=128)


class MemberVerifyResponse(BaseModel):
    eligible: bool
    external_member_id: str | None = None
    display_label: str | None = None
    reason_code: str | None = None


class ReconcileResponse(BaseModel):
    checked: int
    updated: int
    failed: tuple[str, ...] = ()


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def _composition(request: Request):
    composition = getattr(request.app.state, "admin_composition", None)
    if composition is None:
        raise HTTPException(status_code=503, detail={"error": "service_unavailable"})
    return composition


# ---------------------------------------------------------------------------
# 本人照合
# ---------------------------------------------------------------------------
def require_line_inbound(
    request: Request,
    runtime_settings: AdminSettings = Depends(get_admin_runtime_settings),
) -> None:
    """LINE 窓口が持つ Bearer。**設定が無ければ全拒否**（口を開けたままにしない）。"""
    secret = runtime_settings.admin_line_inbound_bearer_token
    if secret is None or not secret.get_secret_value().strip():
        logger.error("ADMIN_LINE_INBOUND_BEARER_TOKEN is not configured; refusing all calls")
        raise HTTPException(status_code=503, detail={"error": "service_unavailable"})
    token = _bearer(request)
    if token is None or not hmac.compare_digest(token, secret.get_secret_value()):
        raise HTTPException(status_code=401, detail={"error": "authorization_required"})


@router.post(
    "/members:verify",
    response_model=MemberVerifyResponse,
    dependencies=[Depends(require_line_inbound)],
)
async def verify_member(request: Request, body: MemberVerifyRequest):
    """会員番号＋氏名の本人照合を ic に中継する。

    ★この関数は `body` の中身をログに書かない。会員番号も氏名も、成功・失敗の別すら
      個人と結びつけて残さない（ic 側が結果の種類だけを記録する）。
    """
    composition = _composition(request)
    try:
        scope = composition.scope_resolver.resolve(body.service_id)
    except OrganizationServiceScopeNotConfiguredError:
        raise HTTPException(status_code=403, detail={"error": "forbidden"})

    gateway = composition.external_business
    verify = getattr(gateway, "verify_member", None)
    if not callable(verify):
        logger.error("external business gateway does not support member verification")
        raise HTTPException(status_code=503, detail={"error": "service_unavailable"})

    try:
        result = await verify(
            external_organization_id=scope.organization_id,
            member_number=body.member_number,
            full_name=body.full_name,
        )
    except ExternalMemberNotFoundError:
        # ★存在しない会員番号を「見つからない」と返さない。不一致と同じ形に畳む
        return MemberVerifyResponse(eligible=False, reason_code="not_matched")
    except ExternalSystemUnavailableError:
        raise HTTPException(
            status_code=503, detail={"error": "external_system_unavailable"}
        )

    if result.get("reason_code") == "rate_limited":
        raise HTTPException(status_code=429, detail={"error": "rate_limited"})
    if not result.get("eligible"):
        return MemberVerifyResponse(eligible=False, reason_code="not_matched")
    return MemberVerifyResponse(
        eligible=True,
        external_member_id=result.get("external_member_id"),
        display_label=result.get("display_label"),
        reason_code=None,
    )


# ---------------------------------------------------------------------------
# reconcile
# ---------------------------------------------------------------------------
async def require_scheduler(
    request: Request,
    runtime_settings: AdminSettings = Depends(get_admin_runtime_settings),
) -> str:
    """Google OIDC の audience と呼び出し元 SA の**両方**を検証する。

    ★片方だけを必須にすると、audience さえ合えば任意の Google OIDC トークンが
      Scheduler として通る。**両方の設定が無ければ全拒否。**
    """
    audience = (runtime_settings.admin_reconcile_audience or "").strip()
    caller = (runtime_settings.admin_reconcile_caller or "").strip()
    if not audience or not caller:
        logger.error(
            "ADMIN_RECONCILE_AUDIENCE / ADMIN_RECONCILE_CALLER are not configured; "
            "refusing all reconcile calls"
        )
        raise HTTPException(status_code=401, detail={"error": "authorization_required"})

    token = _bearer(request)
    if token is None:
        raise HTTPException(status_code=401, detail={"error": "authorization_required"})

    try:
        claims = await asyncio.to_thread(_verify_google_id_token, token, audience)
    except Exception:       # noqa: BLE001 — google-auth の例外は広い
        raise HTTPException(status_code=401, detail={"error": "invalid_token"})

    # ★email_verified は「明示的に True」だけ通す。claim 欠落や非 bool を通すと
    #   fail-closed が崩れる（Google の ID トークンは常に付けてくる）
    if claims.get("email") != caller or claims.get("email_verified") is not True:
        logger.warning("reconcile was called by an unexpected service account")
        raise HTTPException(status_code=403, detail={"error": "forbidden"})
    return caller


def _verify_google_id_token(token: str, audience: str) -> dict:
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, GoogleRequest(), audience=audience)


# 結果が確定した operation。ここに入ったら二度と問い合わせない
TERMINAL_STATUSES = frozenset({
    OperationStatus.COMPLETED,
    OperationStatus.COMPLETED_WITH_ERRORS,
    OperationStatus.CANCELLED,
})


def _awaiting_results(operation) -> bool:
    """送信を要求済みで、まだ結果が確定していない operation か。

    ★「status が SENDING のもの」では拾えない。**本番では SENDING にならない。**
      SENDING を立てるのは `notification_service.process_operation` だけで、それは
      `line_sender` を要求する。本番 composition は `line_sender=None`（LINE へは
      outbox → dispatcher 経由で出す）ので `process_operation` は通らず、送信後の
      operation は **READY のまま** `send_requested_at` だけが入る
      （`send_operation` の docstring 8. と `begin_send_attempt`）。
      SENDING だけを見ると、Scheduler は永久に 0 件を返し続ける。

    そこで「`send_requested_at` が入っていて、結果がまだ確定していない」で拾う。
    送信していない DRAFT / READY は `send_requested_at` が None なので入らない。
    reconciler が COMPLETED / COMPLETED_WITH_ERRORS に落とせば次回から対象外になる。
    """
    return (
        getattr(operation, "send_requested_at", None) is not None
        and operation.status not in TERMINAL_STATUSES
    )


@router.post(
    "/reconcile:run",
    response_model=ReconcileResponse,
    dependencies=[Depends(require_scheduler)],
)
async def run_reconcile(request: Request):
    """送信を要求済みで結果待ちの operation を集め、LINE 側に結果を問い合わせる。

    ★1 件の失敗でループを止めない。止めると、先頭の 1 件が詰まっただけで以降の
      operation が永久に結果待ちのまま残る。失敗は数えて本文とログに出し、**200 を返す**
      （Scheduler は本文を読まないので、可視化は Cloud Run のログと件数で行う）。
    """
    composition = _composition(request)
    repository = composition.boundary.repository
    reconciler = composition.boundary.reconciler

    checked = 0
    updated = 0
    failed: list[str] = []
    for scope in composition.scope_resolver.scopes:
        try:
            operations = await repository.list_operations(scope.service_id)
        except Exception:       # noqa: BLE001
            logger.exception("failed to list operations for a service scope")
            failed.append(f"{scope.service_id}:list")
            continue
        for operation in operations:
            if not _awaiting_results(operation):
                continue
            checked += 1
            try:
                result = await reconciler.reconcile_operation(
                    service_id=scope.service_id, operation_id=operation.operation_id
                )
            except Exception:       # noqa: BLE001
                logger.exception("failed to reconcile operation %s", operation.operation_id)
                failed.append(str(operation.operation_id))
                continue
            if result is not None and result.status in TERMINAL_STATUSES:
                updated += 1

    if failed:
        logger.error("reconcile finished with %d failed operations", len(failed))
    return ReconcileResponse(checked=checked, updated=updated, failed=tuple(failed))

"""ic を外部業務システムとして繋いだときの境界を固定する。

対象は「Admin をこちらの Cloud Run で動かすために足した部分」:

  1. HTTP アダプタの写像と例外（app/adapter/external_business_http.py）
  2. 入口の鍵 = static Bearer（app/api/static_bearer.py）
  3. 本人照合の受け口（app/api/routes/internal_line.py）
  4. reconcile の起動口（同上）
  5. 送信モードの真実性と送信ゲート（app/api/admin_entry_deps.py / routes/admin.py）
  6. demo reset の封印（routes/admin.py）

ネットワークは使わない（httpx.MockTransport）。Google の ID トークン取得は差し替える。
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.adapter.external_business_http import HttpExternalBusinessGateway
from app.api.admin_auth import get_staff_authenticator_http
from app.api.admin_entry_deps import (
    get_admin_application_service,
    line_send_is_live,
)
from app.adapter.staff_auth import DemoStaffAuthenticator
from app.core.settings_admin import AdminSettings
from app.db.engine import set_engine
from app.domain.enums.enums import (
    JobStatus,
    NotificationEligibilityReason,
    OperationStatus,
)
from app.domain.errors.errors import (
    ExternalBusinessNotConfiguredError,
    ExternalJobNotFoundError,
    ExternalSystemUnavailableError,
)
from app.domain.models.external_business import JobSearchQuery
from app.main_admin import create_admin_app

BASE = "https://line-business-api.example.test"
STATIC_TOKEN = "static-token-for-tests"
INBOUND_TOKEN = "line-inbound-token-for-tests"
SCOPES = {"silver-sumida": "sandbox"}


@pytest.fixture(autouse=True)
def _isolate_process_engine():
    set_engine(None)
    yield
    set_engine(None)


@pytest.fixture(autouse=True)
def _no_metadata_server(monkeypatch):
    """ID トークンはメタデータサーバーから取る。テストでは出ていかせない。"""
    monkeypatch.setattr(
        "app.adapter.external_business_http._IdTokenCache._fetch",
        staticmethod(lambda audience: f"id-token-for:{audience}"),
    )


def _settings(**overrides) -> AdminSettings:
    values = dict(
        _env_file=None,
        database_url="postgresql+asyncpg://unused/unused",
        app_env="staging",
        admin_external_business_base_url=BASE,
        admin_external_business_scopes=dict(SCOPES),
        admin_static_bearer_token=SecretStr(STATIC_TOKEN),
        admin_line_inbound_bearer_token=SecretStr(INBOUND_TOKEN),
        admin_line_internal_api_base_url="https://line.internal.example.test",
        admin_line_internal_api_bearer_token=SecretStr("line-token"),
    )
    values.update(overrides)
    return AdminSettings(**values)


def _gateway(handler) -> HttpExternalBusinessGateway:
    return HttpExternalBusinessGateway(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        base_url=BASE,
    )


# ===========================================================================
# 1. HTTP アダプタ
# ===========================================================================
JOB_SUMMARY = {
    "external_job_id": "sandbox-job-01",
    "title": "区民事務所での一般事務",
    "summary": "窓口の受付補助",
    "work_location_summary": "墨田区横川3丁目",
    "work_schedule_summary": "週3日（月・水・金）／9:00〜15:00",
    "application_deadline": None,
    "status": "published",
    "version": "a" * 64,
    "updated_at": "2026-09-15T00:00:00Z",
    "work_days": "週3日（月・水・金）",
    "work_time": "9:00〜15:00",
}


@pytest.mark.asyncio
async def test_アダプタは求人一覧をドメインモデルに写す():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={
            "items": [JOB_SUMMARY], "page": 1, "page_size": 20,
            "total_count": 1, "has_next": False,
        })

    page = await _gateway(handler).search_jobs(
        external_organization_id="sandbox", query=JobSearchQuery()
    )
    assert page.total_count == 1 and page.has_next is False
    job = page.items[0]
    assert job.external_job_id == "sandbox-job-01"
    assert job.status is JobStatus.PUBLISHED
    assert job.updated_at == datetime(2026, 9, 15, tzinfo=timezone.utc)
    assert job.work_days == "週3日（月・水・金）"
    # ★audience は業務 API の URL。Cloud Run の ID トークンを Bearer で送る
    assert seen["auth"] == f"Bearer id-token-for:{BASE}"
    assert seen["url"].startswith(f"{BASE}/v1/orgs/sandbox/jobs")


@pytest.mark.asyncio
async def test_アダプタは契約外の状態を_UNKNOWN_に落とす():
    body = {**JOB_SUMMARY, "status": "ic-side-new-status"}
    page = await _gateway(
        lambda request: httpx.Response(200, json={
            "items": [body], "page": 1, "page_size": 20, "total_count": 1, "has_next": False,
        })
    ).search_jobs(external_organization_id="sandbox", query=JobSearchQuery())
    assert page.items[0].status is JobStatus.UNKNOWN


@pytest.mark.asyncio
async def test_アダプタは求人の_404_を_ExternalJobNotFoundError_にする():
    gateway = _gateway(lambda request: httpx.Response(404, json={"error": "job_not_found"}))
    with pytest.raises(ExternalJobNotFoundError):
        await gateway.get_job_detail(
            external_organization_id="sandbox", external_job_id="missing"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [500, 502, 503])
async def test_アダプタは_5xx_を_ExternalSystemUnavailableError_にする(status):
    gateway = _gateway(lambda request: httpx.Response(status, text="boom"))
    with pytest.raises(ExternalSystemUnavailableError):
        await gateway.get_job_detail(
            external_organization_id="sandbox", external_job_id="sandbox-job-01"
        )


@pytest.mark.asyncio
async def test_アダプタは_401_403_も_503_に倒す():
    """★IAM や SA の設定違いは「外部が不調」に倒す。ただしログには error で残す。"""
    for status in (401, 403):
        gateway = _gateway(lambda request, s=status: httpx.Response(s, text=""))
        with pytest.raises(ExternalSystemUnavailableError):
            await gateway.get_job_detail(
                external_organization_id="sandbox", external_job_id="sandbox-job-01"
            )


@pytest.mark.asyncio
async def test_アダプタは壊れた_JSON_を握りつぶさない():
    gateway = _gateway(lambda request: httpx.Response(200, text="not json"))
    with pytest.raises(ExternalSystemUnavailableError):
        await gateway.get_job_detail(
            external_organization_id="sandbox", external_job_id="sandbox-job-01"
        )


@pytest.mark.asyncio
async def test_アダプタは妥当性確認の理由を写す():
    gateway = _gateway(lambda request: httpx.Response(200, json={
        "external_job_id": "sandbox-job-08",
        "job_eligible": False,
        "current_job_version": "",
        "job_reason_code": "job_closed",
        "members": [
            {"external_member_id": "900001", "eligible": True, "reason_code": None},
            {"external_member_id": "900030", "eligible": False, "reason_code": "member_inactive"},
            {"external_member_id": "900999", "eligible": False, "reason_code": "ic-side-new-reason"},
        ],
        "validated_at": "2026-09-19T00:00:00Z",
        "external_request_id": None,
    }))
    result = await gateway.validate_notification_targets(
        external_organization_id="sandbox",
        external_job_id="sandbox-job-08",
        expected_job_version="",
        external_member_ids=["900001", "900030", "900999"],
    )
    assert result.job_eligible is False
    assert result.job_reason_code is NotificationEligibilityReason.JOB_CLOSED
    # ★求人が無いときは current_job_version が ""（先方モデルは非 null の str）
    assert result.current_job_version == ""
    assert result.members[1].reason_code is NotificationEligibilityReason.MEMBER_INACTIVE
    # 契約外の理由は UNKNOWN に落とす（ic が語を増やしても Admin は落ちない）
    assert result.members[2].reason_code is NotificationEligibilityReason.UNKNOWN


@pytest.mark.asyncio
async def test_アダプタは候補会員の_eligible_と理由の同時保持を避ける():
    """CandidateMember は eligible なら reason_codes が空でなければ ValueError になる。"""
    gateway = _gateway(lambda request: httpx.Response(200, json=[
        {"external_member_id": "900001", "display_label": "佐藤 一郎", "eligible": True,
         "reason_codes": ["should_be_dropped"], "match_rank": 1,
         "line_subject": None, "preference_summary": "おすすめ"},
    ]))
    rows = await gateway.list_candidate_members(
        external_organization_id="sandbox", external_job_id="sandbox-job-01"
    )
    assert rows[0].eligible is True and rows[0].reason_codes == ()
    assert rows[0].display_label == "佐藤 一郎" and rows[0].match_rank == 1


def test_アダプタは_base_url_が無ければ組み立てられない():
    for bad in (None, "", "   ", "not-a-url", "https://host/path?q=1"):
        with pytest.raises(ExternalBusinessNotConfiguredError):
            HttpExternalBusinessGateway(client=httpx.AsyncClient(), base_url=bad)


@pytest.mark.asyncio
async def test_アダプタは_LINE_側の責務を実装しない():
    gateway = _gateway(lambda request: httpx.Response(200, json={}))
    with pytest.raises(NotImplementedError):
        await gateway.check_link_eligibility(
            external_organization_id="sandbox", external_member_id="900001"
        )
    with pytest.raises(NotImplementedError):
        await gateway.list_recommended_jobs(
            external_organization_id="sandbox", external_member_id="900001"
        )


# ===========================================================================
# アプリを組み立てる（合成は差し替える。DB にもネットワークにも出ない）
# ===========================================================================
class _Application:
    """AdminApplicationService の代わり。呼ばれた事実だけを見る。"""

    def __init__(self, targets=(), sent=None):
        self.sent = sent if sent is not None else []
        self._targets = targets

    async def list_jobs(self, service_id):
        return ()

    async def get_operation(self, service_id, operation_id):
        return SimpleNamespace(
            operation=SimpleNamespace(
                operation_id=operation_id, job_id="sandbox-job-01", job_version="v1",
                notification_type="new_job_match",
                message=SimpleNamespace(greeting="g", introduction="i", note="n"),
                status=OperationStatus.READY, validated_at=None, send_requested_at=None,
                completed_at=None, created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ),
            targets=self._targets,
        )

    async def send(self, *, service_id, operation_id, staff_id, request_id):
        self.sent.append(operation_id)

    async def reset(self, service_id):
        return SimpleNamespace(reset=True)


def _readiness_client(*, ready=True, max_recipients=1, error=None):
    from app.contracts.admin_line_internal_v1 import StagingSendReadinessResponse

    async def check(request):
        if error:
            raise error
        return StagingSendReadinessResponse(
            ready=ready, live_send_enabled=ready, max_recipients=max_recipients,
            message_prefix="【検証通知】",
            blocking_reasons=() if ready else ("live_send_disabled",),
        )

    return SimpleNamespace(check_staging_send_readiness=check)


def _composition(*, application=None, readiness=None, repository=None, reconciler=None,
                 external_business=None):
    from app.adapter.admin_scope import ConfiguredOrganizationServiceScopeResolver

    return SimpleNamespace(
        application=application or _Application(),
        boundary=SimpleNamespace(
            client=readiness or _readiness_client(),
            repository=repository,
            reconciler=reconciler,
        ),
        queue=SimpleNamespace(),
        external_business=external_business or SimpleNamespace(),
        dispatch=SimpleNamespace(),
        scope_resolver=ConfiguredOrganizationServiceScopeResolver(dict(SCOPES)),
    )


def _app(settings=None, composition=None):
    settings = settings or _settings()
    composition = composition or _composition()
    app = create_admin_app(
        settings, admin_service_provider=lambda: composition.application
    )
    app.state.admin_composition = composition
    app.dependency_overrides[get_admin_application_service] = (
        lambda: composition.application
    )
    app.dependency_overrides[get_staff_authenticator_http] = (
        lambda: DemoStaffAuthenticator(service_id="silver-sumida")
    )
    return app


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


AUTH = {"Authorization": f"Bearer {STATIC_TOKEN}", "X-Service-ID": "silver-sumida"}


# ===========================================================================
# 2. 入口の鍵（static Bearer）
# ===========================================================================
@pytest.mark.asyncio
async def test_static_bearer_が無ければ_401():
    async with _client(_app()) as client:
        response = await client.get("/admin/jobs", headers={"X-Service-ID": "silver-sumida"})
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "authorization_required"


@pytest.mark.asyncio
async def test_static_bearer_が違えば_401():
    async with _client(_app()) as client:
        response = await client.get(
            "/admin/jobs",
            headers={"Authorization": "Bearer wrong", "X-Service-ID": "silver-sumida"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_static_bearer_が合えば通る():
    async with _client(_app()) as client:
        response = await client.get("/admin/jobs", headers=AUTH)
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_health_は鍵なしで素通し():
    """Cloud Run の死活監視が叩く。ここを閉じるとデプロイが失敗する。"""
    async with _client(_app()) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "owner": "admin"}


@pytest.mark.asyncio
async def test_鍵が未設定なら中間層を入れない():
    """local / test の既存の動きを変えない。"""
    settings = _settings(app_env="local", admin_static_bearer_token=None,
                         admin_external_business_base_url=None)
    async with _client(_app(settings)) as client:
        response = await client.get("/admin/jobs", headers={"X-Service-ID": "silver-sumida"})
    assert response.status_code == 200, response.text


# ===========================================================================
# 3. 本人照合の受け口
# ===========================================================================
class _VerifyGateway:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def verify_member(self, *, external_organization_id, member_number, full_name):
        self.calls.append((external_organization_id, member_number, full_name))
        if self.error:
            raise self.error
        return self.result


VERIFY_PATH = "/internal/v1/members:verify"
VERIFY_AUTH = {"Authorization": f"Bearer {INBOUND_TOKEN}"}
VERIFY_BODY = {"service_id": "silver-sumida", "member_number": "900001",
               "full_name": "佐藤 一郎"}


@pytest.mark.asyncio
async def test_本人照合は_Bearer_が無ければ_401():
    async with _client(_app()) as client:
        response = await client.post(VERIFY_PATH, json=VERIFY_BODY)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_本人照合は職員の鍵では通らない():
    """★職員用の static Bearer と LINE 用の Bearer は別物。使い回せない。"""
    async with _client(_app()) as client:
        response = await client.post(
            VERIFY_PATH, json=VERIFY_BODY,
            headers={"Authorization": f"Bearer {STATIC_TOKEN}"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_本人照合は知らない_service_id_を_403_にする():
    app = _app(composition=_composition(external_business=_VerifyGateway(result={})))
    async with _client(app) as client:
        response = await client.post(
            VERIFY_PATH, json={**VERIFY_BODY, "service_id": "not-configured"},
            headers=VERIFY_AUTH,
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_本人照合が通ると会員番号と表示名を返す():
    gateway = _VerifyGateway(result={
        "eligible": True, "external_member_id": "900001",
        "display_label": "佐藤 一郎", "reason_code": None,
    })
    app = _app(composition=_composition(external_business=gateway))
    async with _client(app) as client:
        response = await client.post(VERIFY_PATH, json=VERIFY_BODY, headers=VERIFY_AUTH)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "eligible": True, "external_member_id": "900001",
        "display_label": "佐藤 一郎", "reason_code": None,
    }
    # service_id は organization_id（ic の tenant_id）に写してから渡す
    assert gateway.calls == [("sandbox", "900001", "佐藤 一郎")]


@pytest.mark.asyncio
async def test_本人照合の不一致は理由を出し分けない():
    """★存在しない会員番号と氏名違いを区別できると、会員番号の存在確認に使える。"""
    not_matched = {"eligible": False, "external_member_id": None,
                   "display_label": None, "reason_code": "not_matched"}
    cases = [
        _VerifyGateway(result=not_matched),
        _VerifyGateway(error=__import__(
            "app.domain.errors.errors", fromlist=["x"]
        ).ExternalMemberNotFoundError("missing")),
    ]
    for gateway in cases:
        app = _app(composition=_composition(external_business=gateway))
        async with _client(app) as client:
            response = await client.post(VERIFY_PATH, json=VERIFY_BODY, headers=VERIFY_AUTH)
        assert response.status_code == 200, response.text
        assert response.json() == {
            "eligible": False, "external_member_id": None,
            "display_label": None, "reason_code": "not_matched",
        }


@pytest.mark.asyncio
async def test_本人照合は回数超過を_429_で返す():
    gateway = _VerifyGateway(result={
        "eligible": False, "external_member_id": None,
        "display_label": None, "reason_code": "rate_limited",
    })
    app = _app(composition=_composition(external_business=gateway))
    async with _client(app) as client:
        response = await client.post(VERIFY_PATH, json=VERIFY_BODY, headers=VERIFY_AUTH)
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_本人照合は受け口のトークンが未設定なら全拒否():
    settings = _settings(admin_line_inbound_bearer_token=None)
    async with _client(_app(settings)) as client:
        response = await client.post(VERIFY_PATH, json=VERIFY_BODY, headers=VERIFY_AUTH)
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_本人照合は氏名をログに書かない(caplog):
    gateway = _VerifyGateway(result={
        "eligible": True, "external_member_id": "900001",
        "display_label": "佐藤 一郎", "reason_code": None,
    })
    app = _app(composition=_composition(external_business=gateway))
    with caplog.at_level("DEBUG"):
        async with _client(app) as client:
            await client.post(VERIFY_PATH, json=VERIFY_BODY, headers=VERIFY_AUTH)
    assert "佐藤" not in caplog.text
    assert "900001" not in caplog.text


# ===========================================================================
# 4. reconcile の起動口
# ===========================================================================
RECONCILE_PATH = "/internal/v1/reconcile:run"
AUDIENCE = "https://admin-backend.example.test"
CALLER = "scheduler-invoker@example.iam.gserviceaccount.com"


class _Repository:
    def __init__(self, operations):
        self.operations = operations
        self.calls = []

    async def list_operations(self, service_id):
        self.calls.append(service_id)
        return self.operations


class _Reconciler:
    def __init__(self, *, fail_on=()):
        self.fail_on = set(fail_on)
        self.calls = []

    async def reconcile_operation(self, *, service_id, operation_id):
        self.calls.append(operation_id)
        if operation_id in self.fail_on:
            raise RuntimeError("LINE internal API is down")
        return SimpleNamespace(status=OperationStatus.COMPLETED)


def _operation(status, *, sent=True):
    """本番では送信しても status は READY のままで、send_requested_at だけが入る。"""
    return SimpleNamespace(
        operation_id=uuid4(),
        status=status,
        send_requested_at=datetime.now(timezone.utc) if sent else None,
    )


def _reconcile_settings(**overrides):
    values = {"admin_reconcile_audience": AUDIENCE, "admin_reconcile_caller": CALLER}
    values.update(overrides)
    return _settings(**values)


@pytest.fixture
def _good_token(monkeypatch):
    def verify(token, audience):
        if token != "scheduler-token" or audience != AUDIENCE:
            raise ValueError("bad token")
        return {"email": CALLER, "email_verified": True}

    monkeypatch.setattr(
        "app.api.routes.internal_line._verify_google_id_token", verify
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["audience", "caller", "both"])
async def test_reconcile_は設定が欠ければ全拒否(missing, _good_token):
    """★片方だけ必須にすると、audience さえ合えば任意の OIDC トークンが通る。"""
    overrides = {}
    if missing in ("audience", "both"):
        overrides["admin_reconcile_audience"] = None
    if missing in ("caller", "both"):
        overrides["admin_reconcile_caller"] = None
    settings = _reconcile_settings(**overrides)
    async with _client(_app(settings)) as client:
        response = await client.post(
            RECONCILE_PATH, headers={"Authorization": "Bearer scheduler-token"}
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_reconcile_は_audience_が違えば_401(monkeypatch):
    def verify(token, audience):
        raise ValueError("audience mismatch")

    monkeypatch.setattr("app.api.routes.internal_line._verify_google_id_token", verify)
    async with _client(_app(_reconcile_settings())) as client:
        response = await client.post(
            RECONCILE_PATH, headers={"Authorization": "Bearer scheduler-token"}
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_reconcile_は別の_SA_を_403(monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.internal_line._verify_google_id_token",
        lambda token, audience: {"email": "someone-else@example.test", "email_verified": True},
    )
    async with _client(_app(_reconcile_settings())) as client:
        response = await client.post(
            RECONCILE_PATH, headers={"Authorization": "Bearer scheduler-token"}
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reconcile_は_static_Bearer_を要求しない(_good_token):
    """★Scheduler は職員の鍵を持たない。要求すると永久に 401 のまま鳴り続ける。"""
    repository = _Repository([])
    composition = _composition(repository=repository, reconciler=_Reconciler())
    async with _client(_app(_reconcile_settings(), composition)) as client:
        response = await client.post(
            RECONCILE_PATH, headers={"Authorization": "Bearer scheduler-token"}
        )
    assert response.status_code == 200, response.text
    assert response.json() == {"checked": 0, "updated": 0, "failed": []}


@pytest.mark.asyncio
async def test_reconcile_は送信済みで未確定のものだけを対象にする(_good_token):
    """★本番の送信は status を SENDING にしない。

    SENDING を立てるのは `process_operation` だけで、それは `line_sender` を要求する。
    本番 composition は `line_sender=None` なので通らず、送信後の operation は
    **READY のまま** `send_requested_at` だけが入る。status だけを見ていると
    Scheduler は永久に 0 件を返し続ける。
    """
    sent_ready = _operation(OperationStatus.READY)            # ← 本番の送信直後の姿
    sending = _operation(OperationStatus.SENDING)             # ← local integration の姿
    skipped = [
        _operation(OperationStatus.DRAFT, sent=False),
        _operation(OperationStatus.READY, sent=False),        # まだ送信していない
        _operation(OperationStatus.COMPLETED),                # 結果が確定済み
        _operation(OperationStatus.COMPLETED_WITH_ERRORS),
        _operation(OperationStatus.CANCELLED),
    ]
    reconciler = _Reconciler()
    composition = _composition(
        repository=_Repository([*skipped, sent_ready, sending]), reconciler=reconciler
    )
    async with _client(_app(_reconcile_settings(), composition)) as client:
        response = await client.post(
            RECONCILE_PATH, headers={"Authorization": "Bearer scheduler-token"}
        )
    assert response.status_code == 200, response.text
    assert response.json() == {"checked": 2, "updated": 2, "failed": []}
    assert reconciler.calls == [sent_ready.operation_id, sending.operation_id]


@pytest.mark.asyncio
async def test_reconcile_は_1件の失敗でループを止めない(_good_token):
    """★止めると、先頭が詰まっただけで以降が永久に結果待ちのまま残る。"""
    first, second, third = (_operation(OperationStatus.READY) for _ in range(3))
    reconciler = _Reconciler(fail_on=[first.operation_id])
    composition = _composition(
        repository=_Repository([first, second, third]), reconciler=reconciler
    )
    async with _client(_app(_reconcile_settings(), composition)) as client:
        response = await client.post(
            RECONCILE_PATH, headers={"Authorization": "Bearer scheduler-token"}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["checked"] == 3 and body["updated"] == 2
    assert body["failed"] == [str(first.operation_id)]
    assert reconciler.calls == [first.operation_id, second.operation_id, third.operation_id]


# ===========================================================================
# 5. 送信モードの真実性と送信ゲート
# ===========================================================================
def test_本番合成は_fake_を名乗らない():
    """★画面に「Fake」と出るのに command が LINE へ飛ぶ、が一番危ない。"""
    assert line_send_is_live(_settings()) is True
    assert line_send_is_live(_settings(app_env="local")) is False
    assert line_send_is_live(_settings(admin_external_business_base_url=None)) is False


@pytest.mark.asyncio
async def test_send_mode_は_LINE_側の_readiness_をそのまま返す():
    composition = _composition(readiness=_readiness_client(ready=True, max_recipients=1))
    async with _client(_app(_settings(), composition)) as client:
        response = await client.get("/admin/line-send-mode", headers=AUTH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "staging_live"
    assert body["ready"] is True and body["max_recipients"] == 1


@pytest.mark.asyncio
async def test_send_mode_は_LINE_に届かなければ_fail_closed():
    composition = _composition(readiness=_readiness_client(error=RuntimeError("down")))
    async with _client(_app(_settings(), composition)) as client:
        response = await client.get("/admin/line-send-mode", headers=AUTH)
    body = response.json()
    assert body["ready"] is False
    assert body["blocking_reasons"] == ["line_readiness_unavailable"]


def _targets(selected: int):
    return tuple(SimpleNamespace(selected=True) for _ in range(selected))


@pytest.mark.asyncio
async def test_送信は_ready_false_なら_409_で止まる():
    """★現行の send 経路は readiness を一切見ずに command を投げていた。"""
    application = _Application(targets=_targets(1))
    composition = _composition(
        application=application, readiness=_readiness_client(ready=False)
    )
    async with _client(_app(_settings(), composition)) as client:
        response = await client.post(
            f"/admin/notification-operations/{uuid4()}/send", headers=AUTH
        )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error"] == "line_not_ready"
    assert application.sent == [], "止めたはずなのに送信に進んでいる"


@pytest.mark.asyncio
async def test_送信は_LINE_に届かないときも_409_で止まる():
    application = _Application(targets=_targets(1))
    composition = _composition(
        application=application, readiness=_readiness_client(error=RuntimeError("down"))
    )
    async with _client(_app(_settings(), composition)) as client:
        response = await client.post(
            f"/admin/notification-operations/{uuid4()}/send", headers=AUTH
        )
    assert response.status_code == 409
    assert application.sent == []


@pytest.mark.asyncio
async def test_送信は_1名制限を超えたら_409_で止まる():
    """★LINE 側の staging sender が制限を持つかに依存せず、Admin 側で止める。"""
    application = _Application(targets=_targets(3))
    composition = _composition(
        application=application, readiness=_readiness_client(ready=True, max_recipients=1)
    )
    async with _client(_app(_settings(), composition)) as client:
        response = await client.post(
            f"/admin/notification-operations/{uuid4()}/send", headers=AUTH
        )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "line_recipient_limit_exceeded"
    assert detail["max_recipients"] == 1 and detail["selected_count"] == 3
    assert application.sent == []


@pytest.mark.asyncio
async def test_送信は_ready_true_で制限内なら通る():
    application = _Application(targets=_targets(1))
    composition = _composition(
        application=application, readiness=_readiness_client(ready=True, max_recipients=1)
    )
    operation_id = uuid4()
    async with _client(_app(_settings(), composition)) as client:
        response = await client.post(
            f"/admin/notification-operations/{operation_id}/send", headers=AUTH
        )
    assert response.status_code == 200, response.text
    assert application.sent == [operation_id]


# ===========================================================================
# 6. demo reset の封印
# ===========================================================================
@pytest.mark.asyncio
async def test_demo_reset_は_staging_では_404():
    """★台帳を丸ごと消す。staging は誰でも Admin ロールになるので封じる。"""
    async with _client(_app(_settings(admin_allow_demo_reset=False))) as client:
        response = await client.post("/admin/demo/reset", headers=AUTH)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_demo_reset_は明示的に許せば通る():
    async with _client(_app(_settings(admin_allow_demo_reset=True))) as client:
        response = await client.post("/admin/demo/reset", headers=AUTH)
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_demo_reset_は_local_では今までどおり使える():
    """先方の手元の開発を壊さない。危ないのは staging / production。"""
    settings = _settings(app_env="local", admin_static_bearer_token=None,
                         admin_external_business_base_url=None)
    async with _client(_app(settings)) as client:
        response = await client.post(
            "/admin/demo/reset", headers={"X-Service-ID": "silver-sumida"}
        )
    assert response.status_code == 200, response.text


# ===========================================================================
# 7. 設定漏れ・契約違反で「開く方向」へ倒れないこと
# ===========================================================================
def test_鍵が無いまま_staging_で起動しない():
    """★Critical: 設定漏れで黙って無認証にしない。

    `get_staff_authenticator_http` は staging を無条件に `DemoStaffAuthenticator`
    （Admin ロール）で通す。鍵が無いまま起動できてしまうと、**誰も気づかないまま**
    URL を知る全員が作成・対象変更・実 LINE 送信を打てる状態で運用が始まる。
    """
    with pytest.raises(RuntimeError, match="ADMIN_STATIC_BEARER_TOKEN"):
        create_admin_app(_settings(admin_static_bearer_token=None))


@pytest.mark.parametrize("environment", ["local", "development", "demo", "test"])
def test_鍵が無くても外に出ない環境は今までどおり起動する(environment):
    app = create_admin_app(_settings(
        app_env=environment, admin_static_bearer_token=None,
        admin_external_business_base_url=None,
    ))
    assert app is not None


@pytest.mark.asyncio
async def test_fake_のときは送信ゲートをかけない():
    """★fake provider は常に ready:false を返す。無条件にゲートをかけると
    **local の Fake 送信フローが必ず 409 になり、先方の手元の確認が壊れる。**"""
    application = _Application(targets=_targets(3))
    settings = _settings(app_env="local", admin_static_bearer_token=None,
                         admin_external_business_base_url=None)
    composition = _composition(
        application=application, readiness=_readiness_client(ready=False)
    )
    operation_id = uuid4()
    async with _client(_app(settings, composition)) as client:
        response = await client.post(
            f"/admin/notification-operations/{operation_id}/send",
            headers={"X-Service-ID": "silver-sumida"},
        )
    assert response.status_code == 200, response.text
    assert application.sent == [operation_id]


def test_production_では平文_HTTP_の業務_API_を拒む():
    """★この URL へ Google の ID トークンを載せて出ていく。設定ミスが平文送信になる。"""
    with pytest.raises(ExternalBusinessNotConfiguredError):
        HttpExternalBusinessGateway(
            client=httpx.AsyncClient(), base_url="http://plain.example.test",
            environment="production",
        )
    # staging までは http を許す（検証環境で困らないように）
    assert HttpExternalBusinessGateway(
        client=httpx.AsyncClient(), base_url="http://plain.example.test",
        environment="staging",
    )


@pytest.mark.asyncio
async def test_契約違反の真偽値を_True_に倒さない():
    """★`bool("false")` は True。外部が壊れた値を返したとき、
    「本人一致」「通知可能」が**開く方向**に倒れてはいけない。"""
    gateway = _gateway(lambda request: httpx.Response(200, json=[
        {"external_member_id": "900001", "display_label": "佐藤 一郎",
         "eligible": "false", "reason_codes": [], "match_rank": 1},
    ]))
    rows = await gateway.list_candidate_members(
        external_organization_id="sandbox", external_job_id="sandbox-job-01"
    )
    assert rows[0].eligible is False

    verify = _gateway(lambda request: httpx.Response(200, json={
        "eligible": "false", "external_member_id": "900001",
        "display_label": "佐藤 一郎", "reason_code": None,
    }))
    result = await verify.verify_member(
        external_organization_id="sandbox", member_number="900001", full_name="佐藤 一郎"
    )
    assert result["eligible"] is False


@pytest.mark.asyncio
async def test_配列の要素が_object_でなければ_503_に倒す():
    """★`.get()` を生で呼ぶと AttributeError が素の 500 になる。"""
    gateway = _gateway(lambda request: httpx.Response(200, json=["not-an-object"]))
    with pytest.raises(ExternalSystemUnavailableError):
        await gateway.list_candidate_members(
            external_organization_id="sandbox", external_job_id="sandbox-job-01"
        )


@pytest.mark.asyncio
async def test_reconcile_は_email_verified_の欠落を通さない(monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.internal_line._verify_google_id_token",
        lambda token, audience: {"email": CALLER},      # email_verified が無い
    )
    async with _client(_app(_reconcile_settings())) as client:
        response = await client.post(
            RECONCILE_PATH, headers={"Authorization": "Bearer scheduler-token"}
        )
    assert response.status_code == 403

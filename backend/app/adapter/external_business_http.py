"""ic（外部業務システム）へ HTTP で問い合わせる ExternalBusinessGateway の実装。

なぜ要るか
----------
現行の Admin には production 向けの External Business provider が無く、
`get_admin_application_service` が 503 を返すだけになっている。会員・求人の正本は
ic（Firestore）側にあり、Admin はその都度問い合わせに来る設計なので、ここが無いと
production / staging では画面が一切動かない。

境界
----
- 呼ぶ先は ic の業務 API（Cloud Run・`/v1/orgs/{organization_id}/...`）。契約は 5 本
- 認証は **Cloud Run の ID トークン**。Cloud Run のメタデータサーバーから
  `audience = 業務 API の URL` で取り、`Authorization: Bearer` で送る
  （依存追加: `google-auth`）
- 外部の応答は**この層でドメイン例外に翻訳する**。上位（application / routes）に
  HTTP の事情を漏らさない

`check_link_eligibility` / `list_recommended_jobs` は現行の Admin から呼ばれない
（LINE 側の責務）。実装せず `NotImplementedError` にして、呼ばれたら気づけるようにする。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from urllib.parse import quote, urlsplit

import httpx

from app.domain.enums.enums import (
    JobStatus,
    NotificationEligibilityReason,
)
from app.domain.errors.errors import (
    ExternalBusinessNotConfiguredError,
    ExternalJobNotFoundError,
    ExternalMemberNotFoundError,
    ExternalSystemUnavailableError,
)
from app.domain.models.external_business import (
    CandidateMember,
    ExternalJobDetail,
    ExternalJobSummary,
    JobSearchQuery,
    PagedExternalJobs,
)
from app.domain.models.notification import (
    MemberValidationResult,
    NotificationValidationResult,
)

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0
# ID トークンの寿命は 1 時間。毎リクエストでメタデータサーバーを叩かずに済むよう
# 少し手前で取り直す（妥当性確認 1 回で 3 本呼ぶため、回数がそのまま効いてくる）
_TOKEN_TTL_SECONDS = 45 * 60


class _IdTokenCache:
    """audience ごとに Cloud Run の ID トークンを持ち回る。

    `fetch_id_token` は同期で外に出ていくので、イベントループを止めないよう
    スレッドに逃がす。
    """

    def __init__(self) -> None:
        self._tokens: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, audience: str) -> str:
        now = time.monotonic()
        cached = self._tokens.get(audience)
        if cached is not None and cached[1] > now:
            return cached[0]
        async with self._lock:
            cached = self._tokens.get(audience)
            if cached is not None and cached[1] > time.monotonic():
                return cached[0]
            token = await asyncio.to_thread(self._fetch, audience)
            self._tokens[audience] = (token, time.monotonic() + _TOKEN_TTL_SECONDS)
            return token

    @staticmethod
    def _fetch(audience: str) -> str:
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token

        return id_token.fetch_id_token(Request(), audience)


def _parse_datetime(value) -> datetime | None:
    """ic は ISO 8601（UTC・末尾 Z）で返す。読めない値は握りつぶさず None にする。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("external business returned an unparsable timestamp")
        return None


def _flag(value) -> bool:
    """★真偽値は本物の bool だけを True にする。

    `bool(value)` だと、契約違反の文字列 `"false"` や `"0"` まで True になる。
    「本人一致」「通知可能」が**開く方向**に倒れるので、bool 以外は False にする。
    """
    return value is True


def _object(body) -> dict:
    """応答は JSON オブジェクトのはず。配列や文字列が来たら「外部が不調」に倒す。"""
    if not isinstance(body, dict):
        raise ExternalSystemUnavailableError(
            "external business returned an unexpected response shape"
        )
    return body


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def _optional_text(value) -> str | None:
    return value if isinstance(value, str) and value else None


def _job_status(value) -> JobStatus:
    """契約外の enum 値は UNKNOWN に落とす（ic が語を増やしても Admin は落ちない）。"""
    try:
        return JobStatus(value)
    except ValueError:
        logger.warning("external business returned an unknown job status")
        return JobStatus.UNKNOWN


def _eligibility_reason(value) -> NotificationEligibilityReason | None:
    if value is None:
        return None
    try:
        return NotificationEligibilityReason(value)
    except ValueError:
        logger.warning("external business returned an unknown eligibility reason")
        return NotificationEligibilityReason.UNKNOWN


class HttpExternalBusinessGateway:
    """ic 業務 API の HTTP アダプタ。

    :param client: 共有の httpx.AsyncClient
    :param base_url: 業務 API の URL。**ID トークンの audience にもなる**
    """

    def __init__(
        self, *, client: httpx.AsyncClient, base_url: str | None, environment: str = "local"
    ) -> None:
        self._client = client
        self._base_url = self._validate_base(base_url, environment)
        self._tokens = _IdTokenCache()

    # -- 契約 5 本 ---------------------------------------------------------
    async def check_link_eligibility(self, *, external_organization_id, external_member_id):
        raise NotImplementedError(
            "link eligibility is owned by the LINE repository, not the Admin boundary"
        )

    async def list_recommended_jobs(self, *, external_organization_id, external_member_id):
        raise NotImplementedError(
            "recommended jobs are owned by the LINE repository, not the Admin boundary"
        )

    async def search_jobs(
        self, *, external_organization_id: str, query: JobSearchQuery
    ) -> PagedExternalJobs:
        params: dict[str, str] = {
            "page": str(query.page),
            "page_size": str(query.page_size),
        }
        if query.keyword:
            params["keyword"] = query.keyword
        if query.statuses:
            params["statuses"] = ",".join(status.value for status in query.statuses)
        if query.updated_from:
            params["updated_from"] = query.updated_from.isoformat()
        if query.updated_to:
            params["updated_to"] = query.updated_to.isoformat()

        body = _object(await self._request(
            "GET", f"/v1/orgs/{_segment(external_organization_id)}/jobs", params=params
        ))
        items = body.get("items")
        if not isinstance(items, list):
            raise ExternalSystemUnavailableError("external business returned an invalid page")
        return PagedExternalJobs(
            items=tuple(self._summary(_object(item)) for item in items),
            page=_int(body.get("page"), query.page),
            page_size=_int(body.get("page_size"), query.page_size),
            total_count=body.get("total_count") if isinstance(body.get("total_count"), int) else None,
            has_next=_flag(body.get("has_next")),
        )

    async def get_job_detail(
        self, *, external_organization_id: str, external_job_id: str
    ) -> ExternalJobDetail:
        body = _object(await self._request(
            "GET",
            f"/v1/orgs/{_segment(external_organization_id)}/jobs/{_segment(external_job_id)}",
            not_found=ExternalJobNotFoundError,
        ))
        conditions = body.get("required_conditions")
        return ExternalJobDetail(
            external_job_id=_text(body.get("external_job_id")),
            title=_text(body.get("title")),
            description=_text(body.get("description")),
            work_location=_optional_text(body.get("work_location")),
            work_schedule_text=_optional_text(body.get("work_schedule_text")),
            application_deadline=_parse_datetime(body.get("application_deadline")),
            required_conditions=(
                tuple(str(item) for item in conditions)
                if isinstance(conditions, list) else ()
            ),
            status=_job_status(body.get("status")),
            version=_text(body.get("version")),
            updated_at=_parse_datetime(body.get("updated_at")),
            staff_notes=_optional_text(body.get("staff_notes")),
            job_url=_optional_text(body.get("job_url")),
        )

    async def list_candidate_members(
        self, *, external_organization_id: str, external_job_id: str
    ) -> list[CandidateMember]:
        body = await self._request(
            "GET",
            f"/v1/orgs/{_segment(external_organization_id)}/jobs"
            f"/{_segment(external_job_id)}/candidate-members",
            not_found=ExternalJobNotFoundError,
        )
        if not isinstance(body, list):
            raise ExternalSystemUnavailableError(
                "external business returned an invalid candidate list"
            )
        return [self._candidate(_object(item)) for item in body]

    async def validate_notification_targets(
        self,
        *,
        external_organization_id: str,
        external_job_id: str,
        expected_job_version: str,
        external_member_ids: list[str],
    ) -> NotificationValidationResult:
        body = _object(await self._request(
            "POST",
            f"/v1/orgs/{_segment(external_organization_id)}/jobs"
            f"/{_segment(external_job_id)}/validate-targets",
            json={
                "expected_job_version": expected_job_version,
                "external_member_ids": list(external_member_ids),
            },
        ))
        members = body.get("members")
        if not isinstance(members, list):
            raise ExternalSystemUnavailableError(
                "external business returned an invalid validation result"
            )
        job_eligible = _flag(body.get("job_eligible"))
        validated_at = _parse_datetime(body.get("validated_at"))
        if validated_at is None:
            raise ExternalSystemUnavailableError(
                "external business returned no validation timestamp"
            )
        return NotificationValidationResult(
            external_job_id=_text(body.get("external_job_id")) or external_job_id,
            job_eligible=job_eligible,
            # ★先方モデルは非 null の str。ic は求人が無いとき "" を返す
            current_job_version=_text(body.get("current_job_version")),
            # eligible のときに理由を持つと dataclass が ValueError を投げる
            job_reason_code=None if job_eligible else _eligibility_reason(body.get("job_reason_code")),
            members=tuple(self._member_validation(_object(item)) for item in members),
            validated_at=validated_at,
            external_request_id=_optional_text(body.get("external_request_id")),
        )

    # -- 本人照合（LINE 初回連携。Admin の受け口から呼ぶ） --------------
    async def verify_member(
        self, *, external_organization_id: str, member_number: str, full_name: str
    ) -> dict:
        """会員番号＋氏名の照合。**氏名も応答もログに書かない。**

        ic 側は不一致の理由を `not_matched` の 1 種類に畳んで返す（存在確認への対策）。
        回数超過は 429 で、ここでは `rate_limited` として上位に渡す。
        """
        body = _object(await self._request(
            "POST",
            f"/v1/orgs/{_segment(external_organization_id)}/members:verify",
            json={"member_number": member_number, "full_name": full_name},
            not_found=ExternalMemberNotFoundError,
            allow_status={429},
        ))
        return {
            "eligible": _flag(body.get("eligible")),
            "external_member_id": _optional_text(body.get("external_member_id")),
            "display_label": _optional_text(body.get("display_label")),
            "reason_code": _optional_text(body.get("reason_code")),
        }

    # -- 写像 --------------------------------------------------------------
    @staticmethod
    def _summary(item: dict) -> ExternalJobSummary:
        return ExternalJobSummary(
            external_job_id=_text(item.get("external_job_id")),
            title=_text(item.get("title")),
            summary=_optional_text(item.get("summary")),
            work_location_summary=_optional_text(item.get("work_location_summary")),
            work_schedule_summary=_optional_text(item.get("work_schedule_summary")),
            application_deadline=_parse_datetime(item.get("application_deadline")),
            status=_job_status(item.get("status")),
            version=_text(item.get("version")),
            updated_at=_parse_datetime(item.get("updated_at")),
            work_days=_optional_text(item.get("work_days")),
            work_time=_optional_text(item.get("work_time")),
        )

    @staticmethod
    def _candidate(item: dict) -> CandidateMember:
        eligible = _flag(item.get("eligible"))
        codes = item.get("reason_codes")
        # eligible のとき reason_codes を持つと dataclass が ValueError を投げる
        reason_codes = () if eligible or not isinstance(codes, list) else tuple(
            str(code) for code in codes
        )
        rank = item.get("match_rank")
        return CandidateMember(
            external_member_id=_text(item.get("external_member_id")),
            display_label=_optional_text(item.get("display_label")),
            eligible=eligible,
            reason_codes=reason_codes,
            match_rank=rank if isinstance(rank, int) else None,
            line_subject=_optional_text(item.get("line_subject")),
            preference_summary=_optional_text(item.get("preference_summary")),
        )

    @staticmethod
    def _member_validation(item: dict) -> MemberValidationResult:
        eligible = _flag(item.get("eligible"))
        return MemberValidationResult(
            external_member_id=_text(item.get("external_member_id")),
            eligible=eligible,
            reason_code=None if eligible else _eligibility_reason(item.get("reason_code")),
        )

    # -- HTTP --------------------------------------------------------------
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        not_found: type[Exception] = ExternalJobNotFoundError,
        allow_status: set[int] | None = None,
    ):
        token = await self._token()
        try:
            response = await self._client.request(
                method,
                f"{self._base_url}{path}",
                params=params,
                json=json,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                timeout=TIMEOUT_SECONDS,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise ExternalSystemUnavailableError(
                "external business transport is unavailable"
            ) from error

        if response.status_code in (401, 403):
            # ★設定事故を隠さない。IAM か SA の指定が違うと全経路がここに落ちる
            logger.error(
                "external business rejected the caller (%s). "
                "Check ALLOWED_CALLER_SA / SELF_URL on the business API and the "
                "run.invoker binding for this service account.",
                response.status_code,
            )
            raise ExternalSystemUnavailableError("external business rejected the caller")
        if response.status_code == 404:
            raise not_found("external business resource was not found")
        if allow_status and response.status_code in allow_status:
            pass
        elif response.status_code >= 500:
            raise ExternalSystemUnavailableError("external business is unavailable")
        elif response.status_code >= 400:
            raise ExternalSystemUnavailableError(
                f"external business rejected the request ({response.status_code})"
            )

        try:
            return response.json()
        except ValueError as error:
            raise ExternalSystemUnavailableError(
                "external business returned an invalid response body"
            ) from error

    async def _token(self) -> str:
        try:
            return await self._tokens.get(self._base_url)
        except Exception as error:      # noqa: BLE001 — google-auth の例外は広い
            logger.error("failed to mint an ID token for the external business API")
            raise ExternalSystemUnavailableError(
                "external business credential is unavailable"
            ) from error

    @staticmethod
    def _validate_base(value: str | None, environment: str = "local") -> str:
        if not value or value != value.strip():
            raise ExternalBusinessNotConfiguredError(
                "external business base URL is not configured"
            )
        try:
            parsed = urlsplit(value)
            parsed.port
        except ValueError as error:
            raise ExternalBusinessNotConfiguredError(
                "external business base URL is invalid"
            ) from error
        if (
            not parsed.scheme
            or not parsed.netloc
            or parsed.scheme not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            # ★production で平文 HTTP を許さない。この URL へ Google の ID トークンを
            #   Authorization で送るので、設定ミスが認証情報と業務データの平文送信になる
            or (environment.strip().lower() == "production" and parsed.scheme != "https")
        ):
            raise ExternalBusinessNotConfiguredError(
                "external business base URL is invalid"
            )
        return value.rstrip("/")


def _segment(value: str) -> str:
    """パスに入る識別子を安全に埋める。**会員番号は URL に乗せない**（本文で送る）。"""
    return quote(str(value), safe="")


def _int(value, fallback: int) -> int:
    return value if isinstance(value, int) and value > 0 else fallback

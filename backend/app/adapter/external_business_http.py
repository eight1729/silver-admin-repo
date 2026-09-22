"""HTTP ExternalBusinessGateway for an external business system.

`CurrentDbExternalBusinessGateway` reads the pre-release Current DB directly and
cannot serve a deployment whose member / job / recommendation system of record
lives elsewhere. This Adapter satisfies the same Port over the external system's
HTTP API.

Boundary:
- Calls the external business API (Cloud Run, `/v1/orgs/{organization_id}/...`).
- Authenticates with a Cloud Run ID token minted from the metadata server for a
  configured audience and sent as `Authorization: Bearer` (requires `google-auth`
  and the `requests` transport it does not itself depend on).
- Translates external responses into domain models and external failures into
  domain errors here, so HTTP concerns never reach application or routes.
- `check_link_eligibility` has no confirmed mapping and raises the "not
  configured" error, exactly as the Current DB Adapter does. It returns no Fake.

Fail-closed policy:
A provider failure must never become a business conclusion. Being valid JSON is
not enough: semantically broken responses (a non-boolean `eligible`, an eligible
result carrying a reason code, a missing identifier, a response for a different
job, a missing `version`) all raise `ExternalSystemUnavailableError`. Folding
them into defaults would turn an outage into "no match" or "safe to notify",
which is a wrong answer rather than a missing one.
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
    MemberVerificationStatus,
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
    ExternalMemberSummary,
    JobSearchQuery,
    LinkEligibility,
    MemberVerificationInput,
    MemberVerificationResult,
    PagedExternalJobs,
)
from app.domain.models.notification import (
    MemberValidationResult,
    NotificationValidationResult,
)

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0
# ID tokens live for an hour. Refresh a little early so a single validation,
# which makes several calls, does not hit the metadata server every time.
_TOKEN_TTL_SECONDS = 45 * 60


class _IdTokenCache:
    """Holds a Cloud Run ID token per audience.

    `fetch_id_token` blocks on network I/O, so it runs in a worker thread rather
    than on the event loop.
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


def _unavailable(reason: str) -> ExternalSystemUnavailableError:
    """One error type for every off-contract response.

    The reason never embeds external values: they may carry member names or
    member numbers.
    """
    return ExternalSystemUnavailableError(f"external business returned {reason}")


def _object(body) -> dict:
    """Responses are JSON objects. An array or a string means the provider is off."""
    if not isinstance(body, dict):
        raise _unavailable("an unexpected response shape")
    return body


def _items(body, field: str) -> list:
    value = body.get(field)
    if not isinstance(value, list):
        raise _unavailable(f"an invalid {field} list")
    return value


def _parse_datetime(value) -> datetime | None:
    """Timestamps arrive as ISO 8601 UTC. Unreadable values become None, not now()."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("external business returned an unparsable timestamp")
        return None


def _decision_flag(value, field: str) -> bool:
    """A boolean that becomes a business decision. Anything but a bool is a failure.

    `bool(value)` or a False default would turn an off-contract response or a
    missing field into the conclusion "not this person" or "not a candidate".
    Zero results and provider failures must stay distinguishable.
    """
    if value is not True and value is not False:
        raise _unavailable(f"a non-boolean {field}")
    return value


def _required_text(value, field: str) -> str:
    """Fields that must be a non-empty string: identifiers and job versions."""
    if not isinstance(value, str) or not value:
        raise _unavailable(f"an invalid {field}")
    return value


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def _optional_text(value) -> str | None:
    return value if isinstance(value, str) and value else None


def _job_status(value) -> JobStatus:
    """Unknown enum values fall back to UNKNOWN so a new status cannot break Admin."""
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
    """HTTP Adapter for the external business API.

    :param client: the shared `httpx.AsyncClient` owned by the app lifespan
    :param base_url: the business API URL. Requests always go here.
    :param audience: ID token audience. Defaults to `base_url`.
    :param environment: `production` refuses plaintext HTTP.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        base_url: str | None,
        audience: str | None = None,
        environment: str = "local",
    ) -> None:
        self._client = client
        self._base_url = self._validate_base(base_url, environment)
        # Destination and audience are separate. Collapsing them would make the
        # audience unconfigurable behind a load balancer or a custom domain.
        self._audience = (audience or "").strip() or self._base_url
        self._tokens = _IdTokenCache()

    # -- members -----------------------------------------------------------
    async def verify_member(
        self,
        *,
        external_organization_id: str,
        verification: MemberVerificationInput,
    ) -> MemberVerificationResult:
        """Match member number + name. Neither the name nor the body is logged.

        The provider collapses every mismatch reason into one, so a caller cannot
        probe which member numbers exist. Rate limiting (429) is not a match
        outcome and surfaces as ExternalSystemUnavailableError.
        """
        body = _object(await self._request(
            "POST",
            f"/v1/orgs/{_segment(external_organization_id)}/members:verify",
            json={
                "member_number": verification.member_number,
                "full_name": verification.name,
            },
        ))
        # A missing or non-boolean flag is not "no match": it is an outage.
        if not _decision_flag(body.get("eligible"), "eligible"):
            return MemberVerificationResult(MemberVerificationStatus.NO_MATCH)
        # A match carrying a mismatch reason is read as neither, for the same
        # reason it is rejected on candidates and validation rows.
        if body.get("reason_code") is not None:
            raise _unavailable("an eligible match with a reason code")
        # A match without an identifier is read as neither match nor mismatch.
        member_id = _required_text(body.get("external_member_id"), "member identifier")
        # display_label is discarded; get_member_summary owns the display name.
        return MemberVerificationResult(MemberVerificationStatus.UNIQUE_MATCH, member_id)

    async def get_member_summary(
        self, *, external_organization_id: str, external_member_id: str
    ) -> ExternalMemberSummary:
        body = _object(await self._request(
            "POST",
            f"/v1/orgs/{_segment(external_organization_id)}/members:summary",
            json={"external_member_id": external_member_id},
            not_found=ExternalMemberNotFoundError,
        ))
        # The port defines this as the projection *of the requested member*, so a
        # summary for anyone else is refused rather than returned: it would show
        # one member's name in answer to a question about another.
        # A provider that canonicalizes member numbers must therefore be given
        # canonical IDs, which is what verify_member hands back.
        returned = _required_text(body.get("external_member_id"), "member identifier")
        if returned != external_member_id:
            raise _unavailable("a summary for a different member")
        return ExternalMemberSummary(
            external_member_id=returned,
            display_label=_optional_text(body.get("display_label")),
        )

    async def check_link_eligibility(
        self, *, external_organization_id: str, external_member_id: str
    ) -> LinkEligibility:
        # No confirmed mapping. Keep the complete port shape while failing
        # explicitly, without Fake data, as the Current DB Adapter does.
        raise ExternalBusinessNotConfiguredError("link eligibility is not configured")

    async def list_recommended_jobs(
        self, *, external_organization_id: str, external_member_id: str
    ) -> list[ExternalJobSummary]:
        body = _object(await self._request(
            "POST",
            f"/v1/orgs/{_segment(external_organization_id)}/members:recommended-jobs",
            json={"external_member_id": external_member_id},
            not_found=ExternalMemberNotFoundError,
        ))
        return list(self._unique_jobs(_items(body, "items")))

    # -- jobs --------------------------------------------------------------
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
        return PagedExternalJobs(
            items=self._unique_jobs(_items(body, "items")),
            page=_int(body.get("page"), query.page),
            page_size=_int(body.get("page_size"), query.page_size),
            total_count=body.get("total_count") if isinstance(body.get("total_count"), int) else None,
            # has_next paginates; it is not a business decision. Defaulting it to
            # False stops early rather than reading past the end.
            has_next=body.get("has_next") is True,
        )

    async def get_job_detail(
        self, *, external_organization_id: str, external_job_id: str
    ) -> ExternalJobDetail:
        body = _object(await self._request(
            "GET",
            f"/v1/orgs/{_segment(external_organization_id)}/jobs/{_job_segment(external_job_id)}",
            not_found=ExternalJobNotFoundError,
        ))
        conditions = body.get("required_conditions")
        return ExternalJobDetail(
            external_job_id=self._same_job(body.get("external_job_id"), external_job_id),
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
            version=_required_text(body.get("version"), "job version"),
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
            f"/{_job_segment(external_job_id)}/candidate-members",
            not_found=ExternalJobNotFoundError,
        )
        if not isinstance(body, list):
            raise _unavailable("an invalid candidate list")
        rows = [self._candidate(_object(item)) for item in body]
        # NotificationService keys candidates by member ID as well, so a repeated
        # member silently wins here too: an ineligible row followed by an
        # eligible one would make a member who must not be contacted a target.
        if len({row.external_member_id for row in rows}) != len(rows):
            raise _unavailable("a duplicate candidate row")
        return rows

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
            f"/{_job_segment(external_job_id)}/validate-targets",
            json={
                "expected_job_version": expected_job_version,
                "external_member_ids": list(external_member_ids),
            },
        ))
        members = self._member_validations(
            _items(body, "members"), external_member_ids
        )
        job_eligible = _decision_flag(body.get("job_eligible"), "job_eligible")
        job_reason = _eligibility_reason(body.get("job_reason_code"))
        # "Safe to send" carrying a reason is read as neither. Dropping the reason
        # and keeping eligible would reach the send decision in notification_service.
        if job_eligible and job_reason is not None:
            raise _unavailable("an eligible job with a reason code")
        # An absent job answers with an empty version, so empty is allowed only
        # when the job is not eligible. A missing or non-string field is not.
        current_version = body.get("current_job_version")
        if not isinstance(current_version, str):
            raise _unavailable("an invalid current job version")
        # Empty is the absent-job answer specifically, not a blanket allowance for
        # any ineligible job: a closed or paused job with no version would be read
        # downstream as a version change.
        if not current_version and job_reason is not NotificationEligibilityReason.JOB_NOT_FOUND:
            raise _unavailable("a job without a current version")
        validated_at = _parse_datetime(body.get("validated_at"))
        if validated_at is None:
            raise _unavailable("no validation timestamp")
        return NotificationValidationResult(
            external_job_id=self._same_job(body.get("external_job_id"), external_job_id),
            job_eligible=job_eligible,
            current_job_version=current_version,
            job_reason_code=job_reason,
            members=members,
            validated_at=validated_at,
            external_request_id=_optional_text(body.get("external_request_id")),
        )

    # -- mapping -----------------------------------------------------------
    @classmethod
    def _unique_jobs(cls, items: list) -> tuple[ExternalJobSummary, ...]:
        """Map job summaries, refusing a job that appears more than once.

        Callers look a job up by ID and take the first match, so a repeated ID
        with different details would build a notification from the stale row.
        """
        summaries = tuple(cls._summary(_object(item)) for item in items)
        if len({summary.external_job_id for summary in summaries}) != len(summaries):
            raise _unavailable("a duplicate job row")
        return summaries

    @classmethod
    def _member_validations(
        cls, rows: list, requested: list[str]
    ) -> tuple[MemberValidationResult, ...]:
        """Map validation rows, requiring exactly the members that were asked about.

        NotificationService keys these by member ID and turns a row it cannot
        find into MEMBER_NOT_FOUND, a business conclusion. So a duplicate (the
        later row silently wins), an answer about someone who was not asked
        about, and a missing answer are all provider failures rather than
        outcomes: otherwise a mixed-up or truncated response tells an operator
        that a real member does not exist.
        """
        results = tuple(cls._member_validation(_object(row)) for row in rows)
        answered = {result.external_member_id for result in results}
        if len(answered) != len(results):
            raise _unavailable("a duplicate member validation row")
        if answered != set(requested):
            raise _unavailable("a validation result for a different set of members")
        return results

    @staticmethod
    def _same_job(value, requested: str) -> str:
        """Confirm the response describes the job that was requested.

        Accepting a mismatched response would judge send eligibility from another
        job's version and candidates.
        """
        if _required_text(value, "job identifier") != requested:
            raise _unavailable("a response for a different job")
        return requested

    @staticmethod
    def _summary(item: dict) -> ExternalJobSummary:
        return ExternalJobSummary(
            external_job_id=_required_text(item.get("external_job_id"), "job identifier"),
            title=_text(item.get("title")),
            summary=_optional_text(item.get("summary")),
            work_location_summary=_optional_text(item.get("work_location_summary")),
            work_schedule_summary=_optional_text(item.get("work_schedule_summary")),
            application_deadline=_parse_datetime(item.get("application_deadline")),
            status=_job_status(item.get("status")),
            # version is non-optional. Letting it through empty would make the
            # staleness check silently pass.
            version=_required_text(item.get("version"), "job version"),
            updated_at=_parse_datetime(item.get("updated_at")),
            work_days=_optional_text(item.get("work_days")),
            work_time=_optional_text(item.get("work_time")),
        )

    @staticmethod
    def _candidate(item: dict) -> CandidateMember:
        eligible = _decision_flag(item.get("eligible"), "eligible")
        codes = item.get("reason_codes")
        if not isinstance(codes, list):
            raise _unavailable("an invalid reason_codes list")
        if eligible and codes:
            raise _unavailable("an eligible candidate with reason codes")
        rank = item.get("match_rank")
        return CandidateMember(
            external_member_id=_required_text(
                item.get("external_member_id"), "member identifier"
            ),
            display_label=_optional_text(item.get("display_label")),
            eligible=eligible,
            reason_codes=tuple(str(code) for code in codes),
            match_rank=rank if isinstance(rank, int) else None,
            # LINE subjects never enter the Admin domain, even when the response
            # carries one.
            line_subject=None,
            preference_summary=_optional_text(item.get("preference_summary")),
        )

    @staticmethod
    def _member_validation(item: dict) -> MemberValidationResult:
        eligible = _decision_flag(item.get("eligible"), "eligible")
        reason = _eligibility_reason(item.get("reason_code"))
        if eligible and reason is not None:
            raise _unavailable("an eligible member with a reason code")
        return MemberValidationResult(
            external_member_id=_required_text(
                item.get("external_member_id"), "member identifier"
            ),
            eligible=eligible,
            reason_code=reason,
        )

    # -- HTTP --------------------------------------------------------------
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        not_found: type[Exception] | None = None,
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
        except httpx.TransportError as error:
            # The base class, not only timeouts and network errors: a protocol
            # or proxy failure must not escape as a generic exception.

            raise ExternalSystemUnavailableError(
                "external business transport is unavailable"
            ) from error

        if response.status_code in (401, 403):
            # Do not hide a configuration accident: a wrong caller identity or
            # audience sends every call down this path.
            logger.error(
                "external business rejected the caller (%s). Check the allowed caller "
                "service account and audience on the business API, and the "
                "run.invoker binding for this service account.",
                response.status_code,
            )
            raise ExternalSystemUnavailableError("external business rejected the caller")
        if response.status_code == 404:
            raise self._not_found(response, not_found)
        if response.status_code >= 500:
            raise ExternalSystemUnavailableError("external business is unavailable")
        if not 200 <= response.status_code < 300:
            # Everything that is not a success, including 3xx and 429. A redirect
            # body is not an answer, and rate limiting is never folded into a
            # match outcome or an empty candidate list.
            raise ExternalSystemUnavailableError(
                f"external business rejected the request ({response.status_code})"
            )

        try:
            return response.json()
        except ValueError as error:
            raise _unavailable("an invalid response body") from error

    @staticmethod
    def _not_found(response: httpx.Response, not_found: type[Exception] | None) -> Exception:
        """Read why the provider answered 404.

        A 404 for an unserved organization is a configuration error, not "this
        member or job does not exist". Conflating them would show a scope
        mismatch to an end user as "you are not a member".
        """
        try:
            error = response.json().get("error")
        except (ValueError, AttributeError):
            error = None
        if error == "organization_not_found":
            logger.error(
                "external business does not serve the configured organization scope. "
                "Check the organization mapping for this service."
            )
            return ExternalSystemUnavailableError(
                "external business organization scope is not served"
            )
        if not_found is None:
            return ExternalSystemUnavailableError(
                "external business rejected the request (404)"
            )
        return not_found("external business resource was not found")

    async def _token(self) -> str:
        try:
            return await self._tokens.get(self._audience)
        except Exception as error:      # noqa: BLE001 - google-auth raises broadly
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
        # A URL cannot contain raw whitespace or control characters, and neither
        # urlsplit nor httpx.URL rejects them: "https://bad host" would survive
        # configuration and fail later as an apparent outage.
        if any(character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F
               for character in value):
            raise ExternalBusinessNotConfiguredError(
                "external business base URL is invalid"
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
            # "https://:443" has a netloc but no host to send anything to.
            or not parsed.hostname
            or parsed.scheme not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            # Refuse plaintext HTTP in production: a Google ID token and business
            # data would otherwise travel in the clear because of a typo.
            or (environment.strip().lower() == "production" and parsed.scheme != "https")
        ):
            raise ExternalBusinessNotConfiguredError(
                "external business base URL is invalid"
            )
        return value.rstrip("/")


# quote() leaves dot segments intact and the HTTP client then resolves them,
# so `/jobs/..` would be sent to `/v1/orgs/{org}` instead.
_UNUSABLE_SEGMENTS = {"", ".", ".."}


def _segment(value: str) -> str:
    """Escape an identifier placed in the path. Member numbers go in the body."""
    text = str(value)
    if text in _UNUSABLE_SEGMENTS:
        # Reached only through an organization scope, which is configuration.
        raise ExternalBusinessNotConfiguredError(
            "external business organization identifier is unusable"
        )
    return quote(text, safe="")


def _job_segment(value: str) -> str:
    """A job identifier that cannot be a path segment names no job.

    The Current DB Adapter treats an unusable job identifier the same way.
    """
    text = str(value)
    if text in _UNUSABLE_SEGMENTS:
        raise ExternalJobNotFoundError("job was not found")
    return quote(text, safe="")


def _int(value, fallback: int) -> int:
    return value if isinstance(value, int) and value > 0 else fallback

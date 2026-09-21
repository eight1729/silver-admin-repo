"""Admin-owned HTTP adapter for the versioned LINE internal contract."""

from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import SecretStr, ValidationError

from app.contracts.admin_line_internal_v1 import (
    LiffDeepLinkRequest,
    LiffDeepLinkResponse,
    LinkageStatusBatchRequest,
    LinkageStatusBatchResponse,
    NotificationCommand,
    NotificationResult,
    StagingSendReadinessRequest,
    StagingSendReadinessResponse,
    SendCapabilityRequest,
    SendCapabilityResponse,
)


class LineInternalApiClientError(Exception):
    pass


class LineInternalApiConfigurationError(LineInternalApiClientError):
    pass


class LineInternalApiRetryableError(LineInternalApiClientError):
    """Acceptance or query outcome is unavailable and may be retried safely."""


class LineInternalApiPermanentError(LineInternalApiClientError):
    pass


class HttpLineInternalApiClient:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        base_url: str | None,
        bearer_token: SecretStr | None,
        environment: str,
    ) -> None:
        self._client = client
        self._base_url = self._validate_base(base_url, environment)
        if bearer_token is None or not bearer_token.get_secret_value().strip():
            raise LineInternalApiConfigurationError(
                "Admin LINE internal API credential is not configured"
            )
        self._token = bearer_token

    async def submit_notification_command(self, command):
        return await self._request(
            "POST", "/internal/v1/notification-commands",
            NotificationResult, expected_status=202,
            json=command.model_dump(mode="json"),
        )

    async def get_notification_result(self, command_id: UUID):
        return await self._request(
            "GET", f"/internal/v1/notification-commands/{command_id}",
            NotificationResult, expected_status=200,
        )

    async def batch_get_linkages(self, request: LinkageStatusBatchRequest):
        return await self._request(
            "POST", "/internal/v1/line-linkages:batch-get",
            LinkageStatusBatchResponse, expected_status=200,
            json=request.model_dump(mode="json"),
        )

    async def resolve_deep_link(self, request: LiffDeepLinkRequest):
        return await self._request(
            "POST", "/internal/v1/liff-deep-links:resolve",
            LiffDeepLinkResponse, expected_status=200,
            json=request.model_dump(mode="json"),
        )

    async def check_staging_send_readiness(
        self, request: StagingSendReadinessRequest
    ) -> StagingSendReadinessResponse:
        return await self._request(
            "POST", "/internal/v1/staging-send-readiness:check",
            StagingSendReadinessResponse, expected_status=200,
            json=request.model_dump(mode="json"),
        )

    async def check_send_capability(self, request: SendCapabilityRequest) -> SendCapabilityResponse:
        return await self._request(
            "POST", "/internal/v1/send-capability:check", SendCapabilityResponse,
            expected_status=200, json=request.model_dump(mode="json"),
        )

    async def _request(self, method, path, model, *, expected_status, json=None):
        try:
            response = await self._client.request(
                method,
                f"{self._base_url}{path}",
                headers={
                    "Authorization": f"Bearer {self._token.get_secret_value()}",
                    "Accept": "application/json",
                },
                json=json,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise LineInternalApiRetryableError(
                "LINE internal API transport is unavailable"
            ) from error
        if response.status_code == 409 or 400 <= response.status_code < 500:
            raise LineInternalApiPermanentError(
                f"LINE internal API rejected the request ({response.status_code})"
            )
        if response.status_code >= 500:
            raise LineInternalApiRetryableError(
                f"LINE internal API is unavailable ({response.status_code})"
            )
        if response.status_code != expected_status:
            raise LineInternalApiPermanentError(
                f"LINE internal API returned an unexpected status ({response.status_code})"
            )
        try:
            return model.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise LineInternalApiRetryableError(
                "LINE internal API returned an invalid contract response"
            ) from error

    @staticmethod
    def _validate_base(value: str | None, environment: str) -> str:
        if not value or value != value.strip():
            raise LineInternalApiConfigurationError(
                "Admin LINE internal API base URL is not configured"
            )
        try:
            parsed = urlsplit(value)
            parsed.port
        except ValueError as error:
            raise LineInternalApiConfigurationError(
                "Admin LINE internal API base URL is invalid"
            ) from error
        if (
            not parsed.scheme or not parsed.netloc or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or (environment.strip().lower() == "production" and parsed.scheme != "https")
            or parsed.scheme not in {"http", "https"}
        ):
            raise LineInternalApiConfigurationError(
                "Admin LINE internal API base URL is invalid"
            )
        return value.rstrip("/")

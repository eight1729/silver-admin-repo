"""Fake implementation of LineMessageGateway for use in tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.domain.models.messaging import JobNotificationMessage, LineSendResult

# Sentinel: distinguishes "not set" from explicit None.
_UNSET = object()


@dataclass
class _Call:
    method: str
    kwargs: dict[str, Any]


class FakeLineMessageGateway:
    """Test double for LineMessageGateway.

    Records every send attempt and returns a deterministic LineSendResult.
    Set ``raise_on_next`` to an exception instance to simulate a send failure
    for the next call (cleared automatically after raising).

    Usage::

        fake = FakeLineMessageGateway()

        # Simulate a transient failure
        from app.domain.errors.errors import LineTemporaryError
        fake.raise_on_next = LineTemporaryError("retry later")

        # After the call succeeds, inspect the recorded send
        call = fake.calls[0]
        assert call.kwargs["service_id"] == "sumida"
        assert call.kwargs["line_subject"] == "U123"
    """

    def __init__(self) -> None:
        self.calls: list[_Call] = []
        # Raise-on-next: set to an exception instance to raise it once, then clear
        self.raise_on_next: BaseException | None = None
        # Ordered, deterministic demo outcomes. None means success; an
        # exception instance is raised for that call. External callers cannot
        # supply this sequence directly.
        self.outcomes: list[BaseException | None] = []
        # If set, use this fixed datetime as accepted_at instead of datetime.now()
        self.fixed_accepted_at: datetime | None = None
        # 3-state line_request_id control:
        #   _UNSET  → auto-generate from request_id ("fake-line-req-{request_id}")
        #   str     → always return that exact string
        #   None    → return None (simulates missing LINE request ID)
        self._line_request_id_override: object = _UNSET

    @property
    def fixed_line_request_id(self) -> str | None | object:
        return self._line_request_id_override

    @fixed_line_request_id.setter
    def fixed_line_request_id(self, value: str | None) -> None:
        self._line_request_id_override = value

    def reset(self) -> None:
        """Clear call history, raise_on_next, fixed_accepted_at, and line_request_id override."""
        self.calls.clear()
        self.raise_on_next = None
        self.outcomes.clear()
        self.fixed_accepted_at = None
        self._line_request_id_override = _UNSET

    async def send_job_notification(
        self,
        *,
        service_id: str,
        line_subject: str,
        message: JobNotificationMessage,
        request_id: str,
    ) -> LineSendResult:
        self.calls.append(
            _Call(
                method="send_job_notification",
                kwargs={
                    "service_id": service_id,
                    "line_subject": line_subject,
                    "message": message,
                    "request_id": request_id,
                },
            )
        )

        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if outcome is not None:
                raise outcome
        elif self.raise_on_next is not None:
            exc = self.raise_on_next
            self.raise_on_next = None
            raise exc

        accepted_at = (
            self.fixed_accepted_at
            if self.fixed_accepted_at is not None
            else datetime.now(tz=timezone.utc)
        )
        if self._line_request_id_override is _UNSET:
            line_request_id: str | None = f"fake-line-req-{request_id}"
        else:
            line_request_id = self._line_request_id_override  # type: ignore[assignment]
        return LineSendResult(
            line_request_id=line_request_id,
            accepted_at=accepted_at,
        )

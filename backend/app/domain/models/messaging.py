from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class LineSendResult:
    line_request_id: str | None
    accepted_at: datetime

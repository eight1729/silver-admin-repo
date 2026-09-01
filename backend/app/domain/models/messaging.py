from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class JobNotificationMessage:
    message_body: str
    job_detail_url: str
    center_name: str
    inquiry_text: str | None


@dataclass(frozen=True, slots=True)
class LineSendResult:
    line_request_id: str | None
    accepted_at: datetime

from typing import Protocol

from app.domain.models.messaging import JobNotificationMessage, LineSendResult


class LineMessageGateway(Protocol):
    """LINE Push メッセージ送信契約。

    - LINE チャンネルアクセストークンは Infrastructure 実装が service_id から内部解決する
    - Application Service はトークンを直接扱わない
    - 送信失敗は LineSendError のサブクラスを送出する
    - LINE SDK 型・dict を公開契約にしない
    """

    async def send_job_notification(
        self,
        *,
        service_id: str,
        line_subject: str,
        message: JobNotificationMessage,
        request_id: str,
    ) -> LineSendResult: ...

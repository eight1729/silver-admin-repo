from typing import Protocol

from app.domain.models.external_business import (
    CandidateMember,
    ExternalJobDetail,
    ExternalJobSummary,
    ExternalMemberSummary,
    MemberVerificationInput,
    MemberVerificationResult,
    JobSearchQuery,
    LinkEligibility,
    PagedExternalJobs,
)
from app.domain.models.notification import NotificationValidationResult


class ExternalBusinessGateway(Protocol):
    """外部業務システムとの通信契約。

    member / job / recommendation の正式な正本は外部業務システムであり、
    LINE 固有データではない。この Port の ID はすべて外部業務システムの
    scope/identifier を表す。LINE subject や LINE credential は扱わない。

    ``external_organization_id`` は外部業務システム上の organization scope、
    ``external_member_id`` は同 scope 内の会員 ID、``external_job_id`` は同
    scope 内の求人 ID である。既存コードが service_id を organization ID として
    渡す箇所は移行対象であり、両 ID が同義であることを契約しない。

    責務:
    - 外部業務システムへのアクセス（DB / API 等の接続方式は Adapter の責務）
    - 外部レスポンスから内部モデルへの変換
    - 外部エラーから Domain 例外への変換

    責務外:
    - service_id から external_organization_id への解決
    - スタッフ認可
    - DB 保存
    - LINE 送信
    - HTTP レスポンス生成
    """

    async def verify_member(
        self,
        *,
        external_organization_id: str,
        verification: MemberVerificationInput,
    ) -> MemberVerificationResult:
        """Match member_number + name without normalization or fuzzy matching.

        Only a unique match returns the stable external member ID. Provider
        failures raise ExternalBusinessError; they are never match outcomes.
        This verifies identity, independently of link eligibility.
        """
        ...

    async def get_member_summary(
        self,
        *,
        external_organization_id: str,
        external_member_id: str,
    ) -> ExternalMemberSummary:
        """Return the minimal display projection for the requested member ID.

        Raise ExternalMemberNotFoundError if absent; other provider failures
        raise ExternalBusinessError (e.g. ExternalSystemUnavailableError).
        """
        ...

    async def check_link_eligibility(
        self,
        *,
        external_organization_id: str,
        external_member_id: str,
    ) -> LinkEligibility: ...

    async def list_recommended_jobs(
        self,
        *,
        external_organization_id: str,
        external_member_id: str,
    ) -> list[ExternalJobSummary]: ...

    async def get_job_detail(
        self,
        *,
        external_organization_id: str,
        external_job_id: str,
    ) -> ExternalJobDetail: ...

    async def search_jobs(
        self,
        *,
        external_organization_id: str,
        query: JobSearchQuery,
    ) -> PagedExternalJobs: ...

    async def list_candidate_members(
        self,
        *,
        external_organization_id: str,
        external_job_id: str,
    ) -> list[CandidateMember]: ...

    async def validate_notification_targets(
        self,
        *,
        external_organization_id: str,
        external_job_id: str,
        expected_job_version: str,
        external_member_ids: list[str],
    ) -> NotificationValidationResult: ...

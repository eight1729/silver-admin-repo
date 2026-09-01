from enum import Enum


class OperationStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    VALIDATING = "validating"
    SENDING = "sending"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    BLOCKED_EXTERNAL_SYSTEM = "blocked_external_system"
    CANCELLED = "cancelled"


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    UNKNOWN = "unknown"
    SKIPPED = "skipped"



class StaffRole(str, Enum):
    VIEWER = "viewer"
    SENDER = "sender"
    # Version 1.3 operator semantics map to the existing Phase 1 sender value.
    OPERATOR = "sender"
    ADMIN = "admin"


class JobStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    PAUSED = "paused"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class LinkEligibilityReason(str, Enum):
    MEMBER_NOT_FOUND = "member_not_found"
    MEMBER_INACTIVE = "member_inactive"
    MEMBER_NOT_LINKABLE = "member_not_linkable"
    ALREADY_LINKED_TO_OTHER_LINE_ACCOUNT = "already_linked_to_other_line_account"
    ALREADY_LINKED_TO_OTHER_MEMBER = "already_linked_to_other_member"
    ORGANIZATION_MISMATCH = "organization_mismatch"
    INVALID_MEMBER_IDENTIFIER = "invalid_member_identifier"
    UNKNOWN = "unknown"


class NotificationEligibilityReason(str, Enum):
    JOB_CLOSED = "job_closed"
    JOB_PAUSED = "job_paused"
    JOB_CANCELLED = "job_cancelled"
    JOB_NOT_FOUND = "job_not_found"
    JOB_VERSION_CHANGED = "job_version_changed"
    MEMBER_NOT_FOUND = "member_not_found"
    MEMBER_INACTIVE = "member_inactive"
    MEMBER_NO_LONGER_CANDIDATE = "member_no_longer_candidate"
    MEMBER_NOTIFICATION_BLOCKED = "member_notification_blocked"
    ORGANIZATION_MISMATCH = "organization_mismatch"
    UNKNOWN = "unknown"

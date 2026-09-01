"""Fixture loader for ExternalBusinessGateway test scenarios.

Converts JSON fixture files into typed domain models and Fake configuration.

Design rules:
- Never returns raw dicts as Port return values
- All datetimes are converted to timezone-aware (UTC)
- JSON lists are converted to tuples where the domain model requires tuples
- Enum values are explicitly validated; unknown values raise FixtureLoadError
- Missing required fields raise FixtureLoadError
- Invalid datetime strings raise FixtureLoadError
- Missing optional fields are NOT substituted with default values
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.domain.enums.enums import JobStatus, LinkEligibilityReason, NotificationEligibilityReason
from app.domain.errors.errors import ExternalSystemUnavailableError
from app.domain.models.external_business import (
    CandidateMember,
    ExternalJobDetail,
    ExternalJobSummary,
    LinkEligibility,
    PagedExternalJobs,
)
from app.domain.models.notification import MemberValidationResult, NotificationValidationResult

_FIXTURE_DIR = Path(__file__).parent

_ALLOWED_ERROR_TYPES = {"ExternalSystemUnavailableError"}


class FixtureLoadError(Exception):
    """Raised when a fixture JSON cannot be parsed into valid domain models.

    This exception lives only in the testing layer and must not be used in
    production code.
    """


@dataclass(frozen=True)
class ExternalBusinessScenario:
    """Loaded scenario ready to configure a FakeExternalBusinessGateway.

    For normal scenarios: domain model fields are populated, error_to_raise is None.
    For error scenarios: error_to_raise is set, domain model fields are None.
    """

    scenario_id: str
    external_organization_id: str
    link_eligibility: LinkEligibility | None
    recommended_jobs: list[ExternalJobSummary] | None
    job_detail: ExternalJobDetail | None
    candidate_members: list[CandidateMember] | None
    validation_result: NotificationValidationResult | None
    error_to_raise: ExternalSystemUnavailableError | None

    @property
    def is_error_scenario(self) -> bool:
        return self.error_to_raise is not None


def load_external_business_scenario(path: Path | str) -> ExternalBusinessScenario:
    """Load a fixture JSON file and return a typed ExternalBusinessScenario.

    Raises FixtureLoadError on any parse, validation, or structural failure.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureLoadError(f"cannot read fixture {path}: {exc}") from exc

    scenario_id = _require_str(raw, "scenario_id", path)
    org_id = _require_str(raw, "external_organization_id", path)

    if "error" in raw:
        error = _parse_error(raw["error"], path)
        return ExternalBusinessScenario(
            scenario_id=scenario_id,
            external_organization_id=org_id,
            link_eligibility=None,
            recommended_jobs=None,
            job_detail=None,
            candidate_members=None,
            validation_result=None,
            error_to_raise=error,
        )

    # Normal scenario – all domain sections are required
    for section in ("link_eligibility", "recommended_jobs", "job_detail", "candidate_members", "validation_result"):
        if section not in raw:
            raise FixtureLoadError(f"fixture {path}: missing required section '{section}'")

    return ExternalBusinessScenario(
        scenario_id=scenario_id,
        external_organization_id=org_id,
        link_eligibility=_parse_link_eligibility(raw["link_eligibility"], path),
        recommended_jobs=_parse_recommended_jobs(raw["recommended_jobs"], path),
        job_detail=_parse_job_detail(raw["job_detail"], path),
        candidate_members=_parse_candidate_members(raw["candidate_members"], path),
        validation_result=_parse_validation_result(raw["validation_result"], path),
        error_to_raise=None,
    )


def apply_to_fake(fake: Any, scenario: ExternalBusinessScenario) -> None:
    """Configure a FakeExternalBusinessGateway from a loaded scenario.

    For error scenarios, sets all raise_on_next_* attributes to the error.
    For normal scenarios, sets all result attributes.

    Note: error scenarios set ALL methods to raise. If only one method
    should raise, set raise_on_next_* directly on the Fake after calling this.
    """
    if scenario.is_error_scenario:
        fake.raise_on_next_check_link_eligibility = scenario.error_to_raise
        fake.raise_on_next_list_recommended_jobs = scenario.error_to_raise
        fake.raise_on_next_get_job_detail = scenario.error_to_raise
        fake.raise_on_next_search_jobs = scenario.error_to_raise
        fake.raise_on_next_list_candidate_members = scenario.error_to_raise
        fake.raise_on_next_validate_notification_targets = scenario.error_to_raise
    else:
        fake.link_eligibility_result = scenario.link_eligibility
        fake.recommended_jobs_result = scenario.recommended_jobs
        fake.job_detail_result = scenario.job_detail
        fake.candidate_members_result = scenario.candidate_members
        fake.validation_result = scenario.validation_result


# ── Internal helpers ──────────────────────────────────────────────────────────

def _require(d: dict, key: str, path: Path) -> Any:
    if key not in d:
        raise FixtureLoadError(f"fixture {path}: missing required field '{key}'")
    return d[key]


def _require_str(d: dict, key: str, path: Path) -> str:
    v = _require(d, key, path)
    if not isinstance(v, str):
        raise FixtureLoadError(f"fixture {path}: '{key}' must be a string, got {type(v).__name__}")
    return v


def _parse_datetime(value: Any, field: str, path: Path) -> datetime:
    if not isinstance(value, str):
        raise FixtureLoadError(f"fixture {path}: '{field}' must be a string datetime, got {type(value).__name__}")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FixtureLoadError(f"fixture {path}: invalid datetime for '{field}': {value!r}") from exc
    if dt.tzinfo is None:
        raise FixtureLoadError(
            f"fixture {path}: datetime '{field}' has no timezone; use UTC suffix Z or +00:00"
        )
    return dt.astimezone(timezone.utc)


def _parse_optional_datetime(value: Any, field: str, path: Path) -> datetime | None:
    if value is None:
        return None
    return _parse_datetime(value, field, path)


def _parse_job_status(value: Any, field: str, path: Path) -> JobStatus:
    if not isinstance(value, str):
        raise FixtureLoadError(f"fixture {path}: '{field}' must be a string, got {type(value).__name__}")
    try:
        return JobStatus(value)
    except ValueError:
        valid = ", ".join(s.value for s in JobStatus)
        raise FixtureLoadError(
            f"fixture {path}: invalid JobStatus {value!r} for '{field}'; valid values: {valid}"
        )


def _parse_link_eligibility_reason(value: Any, field: str, path: Path) -> LinkEligibilityReason:
    if not isinstance(value, str):
        raise FixtureLoadError(f"fixture {path}: '{field}' must be a string")
    try:
        return LinkEligibilityReason(value)
    except ValueError:
        valid = ", ".join(r.value for r in LinkEligibilityReason)
        raise FixtureLoadError(
            f"fixture {path}: invalid LinkEligibilityReason {value!r} for '{field}'; valid: {valid}"
        )


def _parse_notification_eligibility_reason(value: Any, field: str, path: Path) -> NotificationEligibilityReason:
    if not isinstance(value, str):
        raise FixtureLoadError(f"fixture {path}: '{field}' must be a string")
    try:
        return NotificationEligibilityReason(value)
    except ValueError:
        valid = ", ".join(r.value for r in NotificationEligibilityReason)
        raise FixtureLoadError(
            f"fixture {path}: invalid NotificationEligibilityReason {value!r} for '{field}'; valid: {valid}"
        )


def _parse_error(raw: Any, path: Path) -> ExternalSystemUnavailableError:
    if not isinstance(raw, dict):
        raise FixtureLoadError(f"fixture {path}: 'error' must be an object")
    error_type = _require_str(raw, "type", path)
    if error_type not in _ALLOWED_ERROR_TYPES:
        raise FixtureLoadError(
            f"fixture {path}: unsupported error type {error_type!r}; "
            f"allowed: {sorted(_ALLOWED_ERROR_TYPES)}"
        )
    message = raw.get("message", "")
    return ExternalSystemUnavailableError(message)


def _parse_link_eligibility(raw: Any, path: Path) -> LinkEligibility:
    if not isinstance(raw, dict):
        raise FixtureLoadError(f"fixture {path}: 'link_eligibility' must be an object")
    member_id = _require_str(raw, "external_member_id", path)
    eligible = _require(raw, "eligible", path)
    if not isinstance(eligible, bool):
        raise FixtureLoadError(f"fixture {path}: 'link_eligibility.eligible' must be a bool")
    reason_code_raw = _require(raw, "reason_code", path)  # required key, but value may be null
    reason_code = (
        _parse_link_eligibility_reason(reason_code_raw, "link_eligibility.reason_code", path)
        if reason_code_raw is not None
        else None
    )
    checked_at = _parse_datetime(_require(raw, "checked_at", path), "link_eligibility.checked_at", path)
    return LinkEligibility(
        external_member_id=member_id,
        eligible=eligible,
        reason_code=reason_code,
        checked_at=checked_at,
    )


def _parse_job_summary(raw: Any, idx: int, path: Path) -> ExternalJobSummary:
    if not isinstance(raw, dict):
        raise FixtureLoadError(f"fixture {path}: recommended_jobs[{idx}] must be an object")
    return ExternalJobSummary(
        external_job_id=_require_str(raw, "external_job_id", path),
        title=_require_str(raw, "title", path),
        summary=raw.get("summary"),
        work_location_summary=raw.get("work_location_summary"),
        work_schedule_summary=raw.get("work_schedule_summary"),
        application_deadline=_parse_optional_datetime(raw.get("application_deadline"), f"recommended_jobs[{idx}].application_deadline", path),
        status=_parse_job_status(_require(raw, "status", path), f"recommended_jobs[{idx}].status", path),
        version=_require_str(raw, "version", path),
        updated_at=_parse_optional_datetime(raw.get("updated_at"), f"recommended_jobs[{idx}].updated_at", path),
        work_days=raw.get("work_days"),
        work_time=raw.get("work_time"),
    )


def _parse_recommended_jobs(raw: Any, path: Path) -> list[ExternalJobSummary]:
    if not isinstance(raw, list):
        raise FixtureLoadError(f"fixture {path}: 'recommended_jobs' must be an array")
    return [_parse_job_summary(item, i, path) for i, item in enumerate(raw)]


def _parse_job_detail(raw: Any, path: Path) -> ExternalJobDetail:
    if not isinstance(raw, dict):
        raise FixtureLoadError(f"fixture {path}: 'job_detail' must be an object")
    conditions_raw = _require(raw, "required_conditions", path)
    if not isinstance(conditions_raw, list):
        raise FixtureLoadError(f"fixture {path}: 'job_detail.required_conditions' must be an array")
    conditions = tuple(str(c) for c in conditions_raw)
    return ExternalJobDetail(
        external_job_id=_require_str(raw, "external_job_id", path),
        title=_require_str(raw, "title", path),
        description=_require_str(raw, "description", path),
        work_location=raw.get("work_location"),
        work_schedule_text=raw.get("work_schedule_text"),
        application_deadline=_parse_optional_datetime(raw.get("application_deadline"), "job_detail.application_deadline", path),
        required_conditions=conditions,
        status=_parse_job_status(_require(raw, "status", path), "job_detail.status", path),
        version=_require_str(raw, "version", path),
        updated_at=_parse_optional_datetime(raw.get("updated_at"), "job_detail.updated_at", path),
        staff_notes=raw.get("staff_notes"),
        job_url=raw.get("job_url"),
    )


def _parse_candidate_member(raw: Any, idx: int, path: Path) -> CandidateMember:
    if not isinstance(raw, dict):
        raise FixtureLoadError(f"fixture {path}: candidate_members[{idx}] must be an object")
    eligible = _require(raw, "eligible", path)
    if not isinstance(eligible, bool):
        raise FixtureLoadError(f"fixture {path}: candidate_members[{idx}].eligible must be a bool")
    reason_codes_raw = _require(raw, "reason_codes", path)
    if not isinstance(reason_codes_raw, list):
        raise FixtureLoadError(f"fixture {path}: candidate_members[{idx}].reason_codes must be an array")
    reason_codes = tuple(str(r) for r in reason_codes_raw)
    match_rank = raw.get("match_rank")
    return CandidateMember(
        external_member_id=_require_str(raw, "external_member_id", path),
        display_label=raw.get("display_label"),
        eligible=eligible,
        reason_codes=reason_codes,
        match_rank=match_rank,
        line_subject=raw.get("line_subject"),
        preference_summary=raw.get("preference_summary"),
    )


def _parse_candidate_members(raw: Any, path: Path) -> list[CandidateMember]:
    if not isinstance(raw, list):
        raise FixtureLoadError(f"fixture {path}: 'candidate_members' must be an array")
    return [_parse_candidate_member(item, i, path) for i, item in enumerate(raw)]


def _parse_member_validation(raw: Any, idx: int, path: Path) -> MemberValidationResult:
    if not isinstance(raw, dict):
        raise FixtureLoadError(f"fixture {path}: validation_result.members[{idx}] must be an object")
    eligible = _require(raw, "eligible", path)
    if not isinstance(eligible, bool):
        raise FixtureLoadError(f"fixture {path}: validation_result.members[{idx}].eligible must be a bool")
    reason_code_raw = _require(raw, "reason_code", path)
    reason_code = (
        _parse_notification_eligibility_reason(reason_code_raw, f"validation_result.members[{idx}].reason_code", path)
        if reason_code_raw is not None
        else None
    )
    return MemberValidationResult(
        external_member_id=_require_str(raw, "external_member_id", path),
        eligible=eligible,
        reason_code=reason_code,
    )


def _parse_validation_result(raw: Any, path: Path) -> NotificationValidationResult:
    if not isinstance(raw, dict):
        raise FixtureLoadError(f"fixture {path}: 'validation_result' must be an object")
    job_eligible = _require(raw, "job_eligible", path)
    if not isinstance(job_eligible, bool):
        raise FixtureLoadError(f"fixture {path}: 'validation_result.job_eligible' must be a bool")
    job_reason_raw = _require(raw, "job_reason_code", path)
    job_reason_code = (
        _parse_notification_eligibility_reason(job_reason_raw, "validation_result.job_reason_code", path)
        if job_reason_raw is not None
        else None
    )
    members_raw = _require(raw, "members", path)
    if not isinstance(members_raw, list):
        raise FixtureLoadError(f"fixture {path}: 'validation_result.members' must be an array")
    members = tuple(_parse_member_validation(m, i, path) for i, m in enumerate(members_raw))
    return NotificationValidationResult(
        external_job_id=_require_str(raw, "external_job_id", path),
        job_eligible=job_eligible,
        current_job_version=_require_str(raw, "current_job_version", path),
        job_reason_code=job_reason_code,
        members=members,
        validated_at=_parse_datetime(_require(raw, "validated_at", path), "validation_result.validated_at", path),
        external_request_id=raw.get("external_request_id"),
    )

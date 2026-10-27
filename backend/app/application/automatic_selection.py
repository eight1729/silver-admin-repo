"""Admin selection policy and opaque confirmation identity. No personal attributes persist."""
import hashlib
import json
import re
from collections.abc import Mapping


def automatic_context(operation):
    context = (operation.validation_snapshot or {}).get("automatic_selection")
    if context is None:
        return None
    # Re-evaluate transient dependencies and body-only errors; preserve member exclusions.
    return {**context, "excluded": {key: value for key, value in context["excluded"].items()
        if value.get("reason") not in {"external_timeout", "external_rate_limited", "external_invalid_response", "empty_notification_message"}}}


def context_snapshot(operation):
    context = automatic_context(operation)
    return {"automatic_selection": dict(context)} if context is not None else None


def canonical(value):
    if isinstance(value, Mapping):
        return {k: canonical(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonical(v) for v in value]
    return value


def confirmation_identity(operation, targets):
    payload = [str(operation.operation_id), operation.service_id, operation.job_id,
               operation.job_version, operation.message_hash, operation.message_version,
               operation.updated_at.isoformat(), canonical(operation.validation_snapshot),
               sorted((t.member_id, t.selected, t.line_linked) for t in targets)]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def select_automatic_members(candidates):
    eligible = [c for c in candidates if c.recommendation_level == 5 and c.line_linked and c.eligible]
    if any(not c.member_number or not re.fullmatch(r"[0-9]+", c.member_number) for c in eligible):
        raise ValueError("recommended members require numeric member numbers")
    # Length + normalized decimal string avoids both floating point and integer-size limits.
    eligible.sort(key=lambda c: c.member_id)
    eligible.sort(key=lambda c: (len(c.member_number.lstrip("0") or "0"), c.member_number.lstrip("0") or "0"), reverse=True)
    return tuple(c.member_id for c in eligible[:100])

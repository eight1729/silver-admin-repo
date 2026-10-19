"""Read-only population projection. Never infer historical selection from live data."""
from dataclasses import replace
from collections.abc import Mapping
from app.domain.enums.enums import DeliveryStatus, OperationStatus


def selected_deliveries(operation, targets, deliveries):
    deliveries = tuple(deliveries)
    if operation.send_requested_at is None:
        return deliveries
    rows = (operation.validation_snapshot or {}).get("target_results", ())
    if not isinstance(rows, (list, tuple)) or any(
        not isinstance(row, Mapping) or not isinstance(row.get("member_id"), str)
        or type(row.get("selected")) is not bool for row in rows
    ):
        return deliveries
    frozen = {row["member_id"]: row["selected"] for row in rows}
    selected = {target.member_id: target.selected for target in targets}
    # Both fixed representations must agree. Missing/contradictory history is
    # retained as-is and must be reviewed, never silently repaired.
    if not frozen or len(frozen) != len(rows) or len(selected) != len(targets) or frozen != selected:
        return deliveries
    ids = {row.member_id for row in deliveries}
    wanted = {member for member, flag in frozen.items() if flag}
    if not wanted or len(ids) != len(deliveries) or not wanted <= ids or not ids <= set(frozen):
        return deliveries
    for row in deliveries:
        if not frozen[row.member_id] and not (row.status is DeliveryStatus.SKIPPED and row.error_code == "not_selected"):
            return deliveries
        if frozen[row.member_id] and row.error_code == "not_selected":
            return deliveries
    return tuple(row for row in deliveries if row.member_id in wanted)


def projected_operation(operation, deliveries):
    if operation.send_requested_at is None or not deliveries or operation.status is OperationStatus.CANCELLED:
        return operation
    statuses = {row.status for row in deliveries}
    status = (OperationStatus.SENDING if DeliveryStatus.PENDING in statuses else
              OperationStatus.COMPLETED if statuses == {DeliveryStatus.SENT} else OperationStatus.COMPLETED_WITH_ERRORS)
    return replace(operation, status=status)

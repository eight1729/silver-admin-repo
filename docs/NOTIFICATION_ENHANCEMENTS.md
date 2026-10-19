今回の会員連携版・解除・メニュー同期の反映は [統合反映手順](../../silver-line-repo/docs/MEMBER_LIFECYCLE_ROLLOUT.md) に従ってください。旧新strict契約の混在と、世代なし通知の一律補完は禁止です。

# Notification selection, validation and delivery population

Manual selection remains an explicit save. Unsaved/uncertain targets disable
validation and send in both UI policy and handlers. Identity sets, not counts,
are compared. Validation confirmation requires the same operation, input version,
saved selection, returned selected target IDs and validation timestamp. Input
changes (including change-and-revert) invalidate the request; late replies cannot
restore old confirmation or overwrite a newer message.

Only unreserved DRAFT/READY/BLOCKED_EXTERNAL_SYSTEM operations may be edited or
validated, and Delivery/Outbox must both be empty. Existing optimistic operation
comparison and reservation locks remain. Validation clears prior confirmation
before external I/O. Both manual and automatic workflows can save and revalidate
after a transient outage. Only `external_timeout`, `external_rate_limited` and
`external_invalid_response` are removed from historical automatic exclusion
latches; business exclusions, explicit re-inclusions and initial selection count
are preserved. New transient failures are not latched.

Production composition validates the actual final text at creation/save,
preflight and immediately before reservation, using LINE capability prefix and
canonical link. Resolution failure never becomes an estimated send permission.
The complete text is limited to 5,000 UTF-16 units including newlines/prefix/URL.
Overlong input returns 422 / `message_too_long` and remains editable; no truncation.
The UI displays complete length for manual and automatic message editing.

## Population and historical records

C is the stored candidate set; S is selected Target IDs at the atomic send
reservation after confirmation/revalidation; V is selected SEND verdicts.
Only S gets new Delivery records and only V gets Outbox records. S is immutable
after reservation. Initial count, current candidates, V and successful count do
not substitute for S. Selected refusals/unlinked members remain in S.
Pending in S means processing; all S sent means completed; skip/failed/unknown
within S means completed_with_errors. Validation skipped_count uses S as well.

For historical data, a coherent read projection is used: fixed Target flags must
exactly match unique validation snapshot member/selected flags, all S must have
one delivery, and every excluded legacy delivery must be skipped/not_selected.
A selected not_selected row, missing S delivery, duplicate or contradictory
identity disables projection. Uncertain records keep their prior rows/counts/state
and require manual review; no new business state or repair screen is introduced.
When justified, Admin Operation GET and Delivery GET both use the same S rule;
the UI percentages and delivery-derived history follow those returned rows.
Stored legacy rows/audits are not deleted, and a read does not rewrite old status
or fabricate a completion time. Active aggregate updates use the same rule and
the existing atomic aggregate audit. Old audit events remain historical facts.

Before any separately approved permanent correction, export operation status,
send_requested_at, Target member/selected flags, validation target_results,
Delivery IDs/member/status/reason and audit IDs from a backup/read-only session.
Evaluate `selected_deliveries` and `projected_operation` on these saved records;
record original/visible IDs and old/proposed status. Unchanged records require no
write; missing/contradictory evidence must be excluded from correction. Do not use
current business candidates/preferences. The current application already provides
the coherent projection, so permanent backfill is optional, not a rollout prerequisite.
If approved later, lock/recheck the reviewed record set, update only the aggregate
status, preserve completion time and append one idempotent correction audit. Keep
all underlying deliveries, targets and earlier events.

## Deployment/compatibility and manual gates

Deploy the LINE additive schema, pause intake/recovery and drain old LINE, deploy
new LINE, then this Admin Backend/Frontend together. Never mix old and new LINE
workers. See LINE `docs/NOTIFICATION_EXECUTION_UPGRADE.md` for rollback and the
two-system evidence-limited success correction procedure. Terminal LINE success
correction alone does not update an already reconciled Admin delivery.
Internal contract 1.2.1 retains fields/statuses; Admin validation adds optional
validated_at. Old Admin + new LINE lacks Admin fixes/new labels. New Admin + old
LINE lacks LINE execution/fairness/final defense. No new environment variable.

Manual gates: PostgreSQL separate-process claims/expiry and migration idempotency;
old-worker drain and Scheduler single-shot fairness after restart; actual UI
A-to-B unsaved change, input/operation switch, save-response loss, automatic outage
recovery; UTF-16 final text; selected-only percentages/history; approved test LINE
recipient acceptance (not assumed device delivery). Real DB, provider, Scheduler,
deployment and historical data corrections were not executed in this change.

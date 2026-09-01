import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import type { AdminMessage, AdminOperation, AdminValidation } from "../lib/admin-api.ts";
import { createValidationSnapshot, deriveNotificationUiState, isValidationSnapshotCurrent, memberSelectionsEqual, messagesEqual } from "./notification-ui-state.ts";

const message: AdminMessage = { greeting: "挨拶", introduction: "本文", note: "補足" };
const input = (overrides: Partial<Parameters<typeof createValidationSnapshot>[0]> = {}) => ({
  jobId: "JOB-001", selectedMemberIds: ["MEMBER-001"], message,
  notificationLink: "https://example.invalid/liff/jobs/JOB-001", operationId: "OP-001", centerDisplayName: "表示用センター", ...overrides,
});
const operation = (status: AdminOperation["status"] = "ready"): AdminOperation => ({
  operation_id: "OP-001", job_id: "JOB-001", job_version: "v1", notification_type: "new_job_match", message,
  status, target_count: 1, selected_count: 1, validated_at: null, send_requested_at: null, completed_at: null,
  created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
});
const validation: AdminValidation = { operation_id: "OP-001", status: "ready", can_proceed: true, selected_count: 1, sendable_count: 1, skipped_count: 0, reasons: [], version_changed: false, external_system_blocked: false };

test("validation snapshot compares job, member, message, canonical link, and operation", () => {
  const snapshot = createValidationSnapshot(input());
  assert.equal(isValidationSnapshotCurrent(snapshot, input()), true);
  assert.equal(isValidationSnapshotCurrent(snapshot, input({ jobId: "JOB-002" })), false);
  assert.equal(isValidationSnapshotCurrent(snapshot, input({ selectedMemberIds: ["MEMBER-002"] })), false);
  assert.equal(isValidationSnapshotCurrent(snapshot, input({ message: { ...message, note: "変更" } })), false);
  assert.equal(isValidationSnapshotCurrent(snapshot, input({ notificationLink: "https://example.invalid/liff/jobs/JOB-002" })), false);
  assert.equal(isValidationSnapshotCurrent(snapshot, input({ operationId: "OP-002" })), false);
  assert.equal(isValidationSnapshotCurrent(snapshot, input({ centerDisplayName: "別の表示名" })), false);
});

test("same values and member order do not invalidate a validation snapshot", () => {
  const snapshot = createValidationSnapshot(input({ selectedMemberIds: ["MEMBER-002", "MEMBER-001"] }));
  assert.equal(isValidationSnapshotCurrent(snapshot, input({ selectedMemberIds: ["MEMBER-001", "MEMBER-002", "MEMBER-001"], message: { ...message } })), true);
  assert.equal(memberSelectionsEqual(["A", "B"], ["B", "A"]), true);
  assert.equal(messagesEqual(message, { ...message }), true);
});

function derive(overrides: Partial<Parameters<typeof deriveNotificationUiState>[0]> = {}) {
  return deriveNotificationUiState({ hasJob: true, selectedCount: 1, messageValid: true, operation: operation(), validation, validationCurrent: true, validationWasInvalidated: false, busy: false, action: "idle", liveBlocked: false, liveLinkReady: true, hasTerminalDelivery: false, queueFailure: false, ...overrides });
}

test("central button policy covers initial, editing, validatable, validated and stale", () => {
  assert.equal(derive({ hasJob: false, selectedCount: 0, messageValid: false, operation: null, validation: null, validationCurrent: false }).state, "initial");
  assert.equal(derive({ selectedCount: 0, operation: operation("draft"), validation: null, validationCurrent: false }).state, "editing");
  const validatable = derive({ operation: operation("draft"), validation: null, validationCurrent: false });
  assert.equal(validatable.state, "validatable"); assert.equal(validatable.canValidate, true); assert.equal(validatable.canSend, false);
  const validated = derive();
  assert.equal(validated.state, "validated"); assert.equal(validated.canSend, true);
  const stale = derive({ validationCurrent: false, validationWasInvalidated: true });
  assert.equal(stale.state, "stale"); assert.equal(stale.canSend, false);
  const failed = derive({ validation: { ...validation, can_proceed: false } });
  assert.equal(failed.state, "validation_failed"); assert.equal(failed.canSend, false);
});

test("sending, terminal, blocked, queue failure and missing live link cannot send", () => {
  assert.equal(derive({ busy: true, action: "sending" }).state, "sending");
  const sent = derive({ operation: operation("completed"), hasTerminalDelivery: true });
  assert.equal(sent.state, "sent"); assert.equal(sent.canSend, false); assert.equal(sent.canSaveDraft, false);
  const blocked = derive({ liveBlocked: true });
  assert.equal(blocked.state, "blocked"); assert.equal(blocked.canSend, false);
  assert.equal(derive({ queueFailure: true }).canSend, false);
  const missingLink = derive({ liveLinkReady: false });
  assert.equal(missingLink.canValidate, false);
  assert.equal(missingLink.canSend, false);
});

test("restored ready operation without an in-memory snapshot requires validation", () => {
  const restored = derive({ validation: null, validationCurrent: false, validationWasInvalidated: true });
  assert.equal(restored.state, "stale");
  assert.equal(restored.canSend, false);
});

test("page guards job and validate races with app dialogs", async () => {
  const page = await readFile(new URL("./page.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(page, /window\.confirm/);
  assert.match(page, /title="求人を変更しますか？"/);
  assert.match(page, /title="通知テンプレートを変更しますか？"/);
  assert.match(page, /setPendingJobId\(jobId\)/);
  assert.match(page, /setPendingTemplate\(next\)/);
  assert.match(page, /jobRequestSequence\.current \+= 1/);
  assert.match(page, /requestId !== jobRequestSequence\.current/);
  assert.match(page, /linkRequestSequence\.current/);
  assert.match(page, /startedSnapshot = createValidationSnapshot\(validationInputRef\.current\)/);
  assert.match(page, /isValidationSnapshotCurrent\(startedSnapshot, validationInputRef\.current\)/);
  assert.match(page, /workflowLock\.current/);
  assert.match(page, /setSelected\(new Set\(\)\)/);
  assert.match(page, /setDeliveries\(null\)/);
  assert.match(page, /setNotificationLink\(null\)/);
  assert.match(page, /setOperation\(null\)/);
  assert.match(page, /createTemplateMessage\("standard"/);
  assert.match(page, /setSelectedTemplate\("custom"\)/);
});

test("modal supplies labelled focus-managed confirmation behavior", async () => {
  const modal = await readFile(new URL("../components/Modal.tsx", import.meta.url), "utf8");
  assert.match(modal, /aria-labelledby=\{titleId\}/);
  assert.match(modal, /aria-describedby=\{descriptionId\}/);
  assert.match(modal, /e\.key === "Escape"/);
  assert.match(modal, /e\.key === "Tab"/);
  assert.match(modal, /data-modal-initial-focus/);
  assert.match(modal, /previouslyFocused\?\.focus\(\)/);
  assert.match(modal, /onClick=\{onClose\}/);
});

test("history starts a new frontend context without reset or unlink APIs", async () => {
  const history = await readFile(new URL("./history/page.tsx", import.meta.url), "utf8");
  assert.match(history, /新しい通知を作成/);
  assert.match(history, /過去の送信履歴は削除されません/);
  assert.match(history, /sessionStorage\.removeItem\(ADMIN_OPERATION_STORAGE_KEY\)/);
  assert.match(history, /sessionStorage\.removeItem\(ADMIN_SELECTED_MEMBERS_STORAGE_KEY\)/);
  assert.doesNotMatch(history, /adminApi\.reset|unlink/);
});

test("candidate selection handler keeps a single member and preserves validation invalidation", async () => {
  const page = await readFile(new URL("./page.tsx", import.meta.url), "utf8");
  assert.match(page, /selected\.has\(memberId\) \? new Set<string>\(\) : new Set\(\[memberId\]\)/);
  assert.match(page, /setValidationSnapshot\(null\)/);
  assert.match(page, /setValidationInvalidation/);
});

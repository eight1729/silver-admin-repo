import assert from "node:assert/strict";
import test from "node:test";
import { validationMatchesSaved } from "./admin-workflow.ts";
import { finalNotificationText } from "./notification-text.ts";
import { createValidationSnapshot, isValidationSnapshotCurrent, memberSelectionsEqual, deriveNotificationUiState } from "./notification-ui-state.ts";
import type { AdminOperation, AdminValidation } from "../lib/admin-api.ts";

const message = { greeting: "hello", introduction: "job", note: "note" };
const operation: AdminOperation = { operation_id: "op", job_id: "job", job_version: "1", notification_type: "new_job_match",
  message, status: "ready", target_count: 3, selected_count: 1, selected_member_ids: ["A"], validated_at: "2026-10-19T00:00:00Z",
  send_requested_at: null, completed_at: null, created_at: "", updated_at: "" };
const validation: AdminValidation = { operation_id: "op", status: "ready", can_proceed: true, selected_count: 1, sendable_count: 1,
  skipped_count: 0, reasons: [], version_changed: false, external_system_blocked: false, validated_at: operation.validated_at,
  target_results: [{ member_id: "A", disposition: "send", reason: null }] };

test("A saved, B unsaved cannot validate/send; saving B requires B's validation", () => {
  const args = { hasJob: true, selectedCount: 1, messageValid: true, operation, validation, validationCurrent: true,
    validationWasInvalidated: false, busy: false, action: "idle" as const, liveBlocked: false, liveLinkReady: true,
    hasTerminalDelivery: false, queueFailure: false };
  const unsaved = deriveNotificationUiState({ ...args, targetsSaved: memberSelectionsEqual(["B"], operation.selected_member_ids!) });
  assert.equal(unsaved.canValidate, false); assert.equal(unsaved.canSend, false);
  assert.equal(validationMatchesSaved(operation, validation, ["B"]), false);
  const saved = { ...operation, selected_member_ids: ["B"] };
  assert.equal(validationMatchesSaved(saved, validation, ["B"]), false);
  assert.equal(validationMatchesSaved(saved, { ...validation, target_results: [{ member_id: "B", disposition: "send", reason: null }] }, ["B"]), true);
  assert.equal(deriveNotificationUiState({ ...args, targetsSaved: false }).canValidate, false); // save failure/unknown
});

test("stale operation, validation version and input ABA cannot revive confirmation", () => {
  assert.equal(validationMatchesSaved(operation, { ...validation, operation_id: "other" }, ["A"]), false);
  assert.equal(validationMatchesSaved(operation, { ...validation, validated_at: "older" }, ["A"]), false);
  const input = { operationId: "op", jobId: "job", selectedMemberIds: ["A", "B"], message,
    notificationLink: "https://liff.line.me/test/jobs/job", centerDisplayName: "center", inputVersion: 1 };
  const snapshot = createValidationSnapshot(input);
  assert.equal(isValidationSnapshotCurrent(snapshot, { ...input, selectedMemberIds: ["B", "A"] }), true);
  assert.equal(isValidationSnapshotCurrent(snapshot, { ...input, inputVersion: 3 }), false);
  assert.equal(isValidationSnapshotCurrent(snapshot, { ...input, operationId: "other" }), false);
});

test("final UTF-16 length includes normalized local prefix, emoji, URL and separators", () => {
  const mode = { mode: "staging_live" as const, max_recipients: 10, message_prefix: "[TEST]" };
  const body = { ...message, greeting: "[TEST]\n\n[TEST]\n\n😀" };
  const link = "https://liff.line.me/test/jobs/job";
  const final = finalNotificationText(body, link, mode)!;
  assert.equal(final, `[TEST]\n\n😀\n\njob\n\nnote\n${link}`);
  for (const size of [4999, 5000, 5001]) {
    const padded: string = finalNotificationText({ ...body, note: body.note + "x".repeat(size - final.length) }, link, mode)!;
    assert.equal(padded.length <= 5000, size <= 5000);
  }
  assert.equal(finalNotificationText(body, null, mode), null);
  assert.equal(finalNotificationText(body, link, { ...mode, message_prefix: null }), null);
});


test("empty compatibility sections disappear while internal blank lines survive", () => {
  const original = { greeting: "本文\n\n内部\n\n", introduction: " \u2063 ", note: "\u2063" };
  assert.equal(finalNotificationText(original, "https://liff.line.me/example", { mode: "production_live", max_recipients: null, message_prefix: null }), "本文\n\n内部\nhttps://liff.line.me/example");
  assert.equal(original.note, "\u2063");
});


test("Unicode section whitespace follows the same contract as both Python backends", () => {
  const mode = { mode: "production_live" as const, max_recipients: null, message_prefix: null };
  const link = "https://liff.line.me/example";
  assert.equal(finalNotificationText({ greeting: "\ufeff本文\ufeff", introduction: "\u2063", note: "\u2063" }, link, mode), `本文\n${link}`);
  assert.equal(finalNotificationText({ greeting: "\u0085本文\u0085", introduction: "\u2063", note: "\u2063" }, link, mode), `\u0085本文\u0085\n${link}`);
  for (const prefix of [null, "[TEST]"]) for (const size of [4999, 5000, 5001]) {
    const cap = { ...mode, mode: prefix ? "staging_live" as const : "production_live" as const, message_prefix: prefix };
    const base = { greeting: "\ufeff😀\ufeff", introduction: "\u2063", note: "\u2063" };
    const remaining = size - finalNotificationText(base, link, cap)!.length;
    const final = finalNotificationText({ ...base, greeting: `\ufeff😀${"a".repeat(remaining)}\ufeff` }, link, cap)!;
    assert.equal(final.length, size);
    assert.equal(final.length <= 5000, size <= 5000);
  }
});

import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { notificationEntryUrl, orderAutomaticCandidates, parseNotificationEntry } from "./automatic-workflow.ts";
import type { AdminCandidate } from "../lib/admin-api.ts";

const candidate = (id: string, number: string | null, level: number | null): AdminCandidate => ({
  member_id: id, member_number: number, recommendation_level: level, display_name: "架空会員",
  line_linked: true, eligible: true, reason: null, selected: false,
});

test("automatic/manual entry preserves ID, rejects malformed intent, and supports direct entry", () => {
  for (const mode of ["auto", "manual"] as const) {
    const url = notificationEntryUrl(mode, "a1b2-001");
    assert.deepEqual(parseNotificationEntry(url.slice(url.indexOf("?"))), { mode, jobId: "a1b2-001" });
  }
  assert.deepEqual(parseNotificationEntry(""), { mode: null, jobId: null });
  for (const query of ["?mode=bad", "?mode=auto&jobId=../x", "?mode=auto&jobId=", "?mode=auto&mode=manual", "?jobId=a&jobId=b"])
    assert.deepEqual(parseNotificationEntry(query), { mode: null, jobId: null });
});

test("editing order is selected first then level then exact numeric number then stable identity", () => {
  const items = [candidate("b", "0009", 5), candidate("a", "9", 5), candidate("low", "9999", 1),
    candidate("huge", "999999999999999999999999999999", 5), candidate("missing", null, null)];
  assert.deepEqual(orderAutomaticCandidates(items, new Set(["low"])).map(c => c.member_id), ["low", "huge", "a", "b", "missing"]);
  assert.equal(items[0].member_number, "0009");
  assert.equal(orderAutomaticCandidates(Array.from({ length: 101 }, (_, i) => candidate(String(i), String(i), 5)), new Set()).length, 101);
});

test("persisted operation, automatic validation, token send, and explicit exclusions are wired", () => {
  const source = readFileSync(new URL("./AutomaticNotification.tsx", import.meta.url), "utf8");
  const create = source.indexOf("await adminApi.createOperation");
  const store = source.indexOf("storeOperation(op)", create);
  const targets = source.indexOf("await adminApi.updateTargets", store);
  const save = source.indexOf("await adminApi.updateOperation", targets);
  const validate = source.indexOf("await adminApi.validate", save);
  assert.ok(create < store && store < targets && targets < save && save < validate);
  assert.match(source, /adminApi.send\(confirmation.operation_id, confirmation.confirmation_token\)/);
  assert.match(source, /if \(!confirmation\?\.confirmation_token \|\| !canSend \|\| lock.current\) return/);
  assert.match(source, /setConfirmation\(null\)/);
  assert.match(source, /new Set\(restoredIds\)/);
  assert.match(source, /storeOperation\(saved\)/);
  assert.match(source, /excluded.current.has\(id\)/);
  const storageWrites = source.split(/\r?\n/).filter(line => line.includes("sessionStorage.setItem"));
  assert.deepEqual(storageWrites, ["    sessionStorage.setItem(AUTO_OPERATION_KEY, value.operation_id); // ID only, never display attributes."]);
  assert.match(source, /mobile_phone_last4 \?\? "未登録"/);
  assert.doesNotMatch(source, /phone_home|phone_mobile_normalized/);
  assert.match(source, /confirmation.selected_count/);
  assert.match(source, /confirmation.excluded_count/);
  assert.doesNotMatch(source, /skipped_count/);
});

test("manual entry, published-only cards, shared panels, and scrolling confirmation remain", () => {
  const page = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
  const jobs = readFileSync(new URL("./jobs/page.tsx", import.meta.url), "utf8");
  const css = readFileSync(new URL("./admin.css", import.meta.url), "utf8");
  assert.match(page, /<ManualAdminPage initialJobId=\{jobId\}/);
  assert.match(page, /requestJobSelection\(initialJobId\)/);
  assert.match(jobs, /SelectionModeDialog/);
  assert.match(jobs, /notificationEntryUrl\(mode, pendingJob\)/);
  assert.match(jobs, /disabled=\{job.status !== "published"\}/);
  assert.match(css, /\.automatic-recipient-list \{[^}]*max-height:[^}]*overflow-y: auto/);
});

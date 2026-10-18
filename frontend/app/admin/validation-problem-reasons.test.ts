import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { validationProblemReasons } from "./validation-problem-reasons.ts";
import { notificationReasonLabel } from "./notification-reasons.ts";

test("successful validation retains counts and reasons but has no unselected problem", () => {
  const validation = Object.freeze({ selected_count: 1, sendable_count: 1,
    can_proceed: true, reasons: Object.freeze(["not_selected"]) });
  assert.deepEqual(validationProblemReasons(validation.reasons), []);
  assert.deepEqual(validation, { selected_count: 1, sendable_count: 1,
    can_proceed: true, reasons: ["not_selected"] });
});

test("existing problem reasons are preserved without an allowlist", () => {
  const reasons = ["line_not_linked", "member_ineligible", "job_closed",
    "job_version_changed", "empty_notification_message", "no_sendable_targets"];
  assert.deepEqual(validationProblemReasons(reasons), reasons);
  assert.deepEqual(validationProblemReasons(["unrecognized_reason"]), ["unrecognized_reason"]);
});

test("multiple unselected reasons never become problem details", () => {
  assert.deepEqual(validationProblemReasons(["not_selected", "not_selected"]), []);
  assert.deepEqual(validationProblemReasons([]), []);
});

test("mixed reasons retain actual problems and their order", () => {
  assert.deepEqual(validationProblemReasons([
    "not_selected", "line_not_linked", "not_selected", "job_closed",
  ]), ["line_not_linked", "job_closed"]);
});

test("SendOverview filters only detail reasons and keeps success and label rendering", async () => {
  const source = await readFile(new URL("./MajorPanels.tsx", import.meta.url), "utf8");
  const overview = source.slice(source.indexOf("function SendOverview("), source.indexOf("function SendActionButtons("));
  assert.match(overview, /validationProblemReasons\(validation\.reasons\)\.forEach\(\(reason\) => problems\.add\(safeReasonLabel\(reason\)\)\)/);
  assert.doesNotMatch(overview, /validation\??\.reasons\.forEach/);
  assert.match(overview, /validation\.can_proceed && !hasProblem/);
  assert.match(overview, /validated \? \{ icon: "✓", text: validation!\.selected_count > validation!\.sendable_count \? "除外あり・送信可能者を確認" : "問題ありません"/);
  assert.match(overview, /problems\.size > 0 && <div className="send-problem-details"/);
  assert.match(source, /import \{ notificationReasonLabel as safeReasonLabel \} from "\.\/notification-reasons"/);
  assert.equal(notificationReasonLabel("line_not_linked"), "LINE未連携");
  assert.equal(notificationReasonLabel("job_closed"), "求人募集終了");
  assert.equal(notificationReasonLabel("job_version_changed"), "求人情報更新あり");
});

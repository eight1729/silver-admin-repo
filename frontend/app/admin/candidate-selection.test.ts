import assert from "node:assert/strict";
import test from "node:test";
import { toggleCandidateSelection } from "./candidate-selection.ts";
import { canAttemptSend, safetyPrefix, sendWarning } from "./send-capability.ts";

test("production toggle preserves all other members and original Set", () => {
  let selected = new Set<string>();
  for (const [id, expected] of [["A", ["A"]], ["B", ["A", "B"]], ["C", ["A", "B", "C"]], ["B", ["A", "C"]]] as const) {
    const previous = [...selected];
    const next = toggleCandidateSelection(selected, id, null);
    assert.deepEqual([...selected], previous);
    assert.deepEqual([...next], expected);
    selected = next;
  }
});

test("finite capability refuses addition without replacing, but always permits removal", () => {
  const selected = toggleCandidateSelection(new Set(), "A", 1);
  assert.deepEqual([...toggleCandidateSelection(selected, "B", 1)], ["A"]);
  assert.deepEqual([...toggleCandidateSelection(selected, "A", 1)], []);
  assert.deepEqual([...toggleCandidateSelection(new Set(["A", "B"]), "C", 2)], ["A", "B"]);
  assert.deepEqual([...toggleCandidateSelection(new Set(["A", "B"]), "A", 1)], ["B"]);
});

test("production count is unlimited while staging send limit and warnings stay intact", () => {
  const production = { mode: "production_live" as const, ready: true, live_send_enabled: true, max_recipients: null, message_prefix: null };
  assert.equal(canAttemptSend(production, 3), true);
  assert.equal(safetyPrefix(production), "");
  assert.doesNotMatch(sendWarning(production), /1名|限定/);
  const staging = { ...production, mode: "staging_live" as const, max_recipients: 1, message_prefix: "[TEST]" };
  assert.equal(canAttemptSend(staging, 2), false);
  assert.match(sendWarning(staging), /最大1名・LINE側の許可対象に限定/);
  for (const mode of [{ ...production, ready: false }, { ...production, mode: "disabled" as const }, null]) {
    assert.equal(canAttemptSend(mode, 3), false);
  }
});

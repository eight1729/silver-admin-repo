import assert from "node:assert/strict";
import { test } from "node:test";
import { canAttemptSend, modePresentation, safetyPrefix, sendWarning } from "./send-capability.ts";
import { getBlockingReasonMessage } from "./blocking-reasons.ts";
import type { AdminLineSendMode } from "../lib/admin-api";
import { readFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import ts from "typescript";

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const modules = new Map<string, any>();
function loadComponent(path: string): any {
  if (modules.has(path)) return modules.get(path);
  const module = { exports: {} };
  modules.set(path, module.exports);
  const code = ts.transpileModule(readFileSync(path, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  vm.runInThisContext(`(function(require,module,exports){${code}\n})`)(
    (name: string) => {
      if (!name.startsWith(".")) return require(name);
      const base = resolve(dirname(path), name);
      return loadComponent([`${base}.ts`, `${base}.tsx`].find(existsSync)!);
    }, module, module.exports,
  );
  return module.exports;
}
const { SendConfirmationPanel } = loadComponent(resolve(here, "MajorPanels.tsx"));
const { createElement } = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

for (const [mode, ready, allowed, label] of [
  ["fake", true, true, "Fake"], ["disabled", false, false, "LINE送信は無効"],
  ["staging_live", true, true, "限定実LINE送信"], ["staging_live", false, false, "LINE送信設定未完了"],
  ["production_live", true, true, "実LINE送信"], ["production_live", false, false, "LINE送信設定未完了"],
  ["unavailable", false, false, "LINE送信状態を確認できません"],
] as const) {
  test(`${mode} ready=${ready}: label, warning and send gate`, () => {
    const value: AdminLineSendMode = { mode, ready, live_send_enabled: true, max_recipients: null, message_prefix: null };
    assert.equal(canAttemptSend(value, 1), allowed);
    assert.equal(modePresentation(value).label, label);
    assert.ok(sendWarning(value).includes(label));
    if (mode !== "fake") assert.doesNotMatch(sendWarning(value), /Fake/);
    if (mode === "production_live") assert.doesNotMatch(sendWarning(value), /検証|送信なし|送信は行いません/);
    const html = renderToStaticMarkup(createElement(SendConfirmationPanel, {
      operation: { selected_count: 1 }, validation: { can_proceed: true, sendable_count: 1, reasons: [] },
      candidates: [], selected: new Set(["test-member"]), save: async () => {}, send: async () => {},
      revalidate: async () => {}, busy: false, canSaveDraft: true, canValidate: true,
      canSend: canAttemptSend(value, 1), validationCurrent: true, action: "idle", targets: () => {},
      lineSendMode: value, queueFailure: false,
    }));
    assert.ok(html.includes(label));
    const sendButton = html.match(/<button[^>]*class="admin-button send-primary compact-send-primary"[^>]*>/)?.[0];
    assert.ok(sendButton);
    assert.equal(sendButton.includes("disabled"), !allowed);
    if (mode !== "fake") assert.doesNotMatch(html, /Fake/);
  });
}

test("maximum applies to sendable count and prefix only belongs to staging", () => {
  const value: AdminLineSendMode = { mode: "staging_live", ready: true, live_send_enabled: true, max_recipients: 1, message_prefix: "【検証】" };
  assert.equal(canAttemptSend(value, 1), true);
  assert.equal(canAttemptSend(value, 2), false);
  assert.match(modePresentation(value).detail, /最大1名/);
  assert.equal(safetyPrefix(value), "【検証】");
  assert.equal(safetyPrefix({ ...value, mode: "production_live" }), "");
  assert.equal(canAttemptSend({ ...value, live_send_enabled: false }, 1), false);
  assert.equal(canAttemptSend(null), false);
  assert.equal(canAttemptSend({ ...value, blocking_reasons: ["live_send_disabled"] }), false);
  assert.doesNotMatch(getBlockingReasonMessage("https://private/token"), /private|https|token/);
});

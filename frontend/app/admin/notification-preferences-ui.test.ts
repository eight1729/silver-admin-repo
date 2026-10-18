import assert from "node:assert/strict";
import test from "node:test";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

// Render the actual components and their local modules, without Next startup or dotenv.
const require = createRequire(import.meta.url);
const cache = new Map<string, any>();
function load(path: string): any {
  const file = [path, `${path}.tsx`, `${path}.ts`].find(name => existsSync(name))!;
  if (cache.has(file)) return cache.get(file);
  const module = { exports: {} };
  cache.set(file, module.exports);
  const code = ts.transpileModule(readFileSync(file, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  new Function("require", "module", "exports", code)((id: string) => id.startsWith(".") ? load(resolve(dirname(file), id)) : require(id), module, module.exports);
  return module.exports;
}
const { SendConfirmationPanel } = load(fileURLToPath(new URL("./MajorPanels.tsx", import.meta.url)));
const { DeliverySummaryPanel } = load(fileURLToPath(new URL("./LowerPanels.tsx", import.meta.url)));
const reasons = ["notification_opted_out", "notification_preferences_unanswered", "line_not_linked", "notification_preferences_unavailable"];
const numbers = ["0007", "000008", "9".repeat(100), "0010"];
function review(sendable: number) {
  return renderToStaticMarkup(React.createElement(SendConfirmationPanel, {
    operation: { selected_count: 5, status: "ready" },
    validation: { selected_count: 5, sendable_count: sendable, can_proceed: sendable > 0, reasons: [],
      target_results: reasons.map((reason, index) => ({ member_id: `id-${index}`, reason, disposition: "skip" })) },
    candidates: numbers.map((member_number, index) => ({ member_id: `id-${index}`, member_number, line_linked: index !== 2 })),
    selected: new Set(numbers.map((_, index) => `id-${index}`)),
    validationCurrent: true, action: "idle", canSend: sendable > 0, busy: false,
    lineSendMode: { mode: "production_live", ready: true, live_send_enabled: true, max_recipients: null },
    save() {}, send() {}, revalidate() {}, targets() {},
  }));
}

test("manual validation renders exact member numbers, counts, reasons and explicit subset confirmation", () => {
  const html = review(1);
  for (const number of numbers) assert.ok(html.includes(number));
  for (const label of ["就業通知の受信拒否", "通知アンケート未回答", "LINE未連携", "受信設定を確認できない", "送信不可：4名", "除外理由を確認して送信可能な1名に送信"]) assert.ok(html.includes(label), label);
});

test("zero sendable targets leaves the send button disabled", () => {
  assert.match(review(0), /class="admin-button send-primary compact-send-primary"[^>]*disabled=""/);
});

test("terminal refusal is not shown as successful sending and pending remains accepted", () => {
  const render = (status: string, reason_code: string | null) => renderToStaticMarkup(React.createElement(DeliverySummaryPanel, {
    operation: { operation_id: "op" }, deliveries: { summary: {}, items: [{ delivery_id: "d", member_id: "0007", status, reason_code }] },
    loading: false, error: "", retry() {},
  }));
  for (const reason of reasons.slice(0, 2)) {
    const html = render("failed", reason);
    assert.match(html, /配信処理終了：実送信成功 0件/);
    assert.match(html, /未送信/);
    assert.match(html, reason === reasons[0] ? /受信拒否/ : /アンケート未回答/);
  }
  assert.match(render("sent", null), /実送信成功 1件/);
  assert.match(render("pending", null), /送信受付済み・配信処理中/);
  assert.match(render("unknown", "line_unknown_result"), /結果不明・自動再送なし/);
});

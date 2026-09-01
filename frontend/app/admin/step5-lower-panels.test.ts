import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import type { AdminDeliveries, AdminOperation } from "../lib/admin-api.ts";
import { createDeliveryGradient, summarizeDeliveries } from "./delivery-summary.ts";
import { containsNewHistory, paginateHistory } from "./history-pagination.ts";
import { buildOperationHistory, type SessionHistoryEvent } from "./operation-history.ts";

const operation = (overrides: Partial<AdminOperation> = {}): AdminOperation => ({
  operation_id: "OP-A", job_id: "JOB-A", job_version: "v1", notification_type: "new_job_match",
  message: { greeting: "挨拶", introduction: "本文", note: "補足" }, status: "completed_with_errors",
  target_count: 5, selected_count: 5, validated_at: "2026-08-01T01:00:00Z", send_requested_at: "2026-08-01T02:00:00Z", completed_at: "2026-08-01T03:00:00Z",
  created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T03:00:00Z", ...overrides,
});

const deliveries: AdminDeliveries = {
  items: [
    { delivery_id: "D1", member_id: "M1", status: "sent", reason_code: null, created_at: "2026-08-01T02:00:00Z", sent_at: "2026-08-01T02:10:00Z", updated_at: "2026-08-01T02:10:00Z" },
    { delivery_id: "D2", member_id: "M2", status: "failed", reason_code: null, created_at: "2026-08-01T02:00:00Z", sent_at: null, updated_at: "2026-08-01T02:20:00Z" },
    { delivery_id: "D3", member_id: "M3", status: "unknown", reason_code: null, created_at: "2026-08-01T02:00:00Z", sent_at: null, updated_at: "2026-08-01T02:30:00Z" },
    { delivery_id: "D4", member_id: "M4", status: "skipped", reason_code: null, created_at: "2026-08-01T02:00:00Z", sent_at: null, updated_at: "2026-08-01T02:40:00Z" },
    { delivery_id: "D5", member_id: "M5", status: "pending", reason_code: null, created_at: "2026-08-01T02:00:00Z", sent_at: null, updated_at: "2026-08-01T02:00:00Z" },
  ],
  summary: { sent: 1, failed: 1, unknown: 1, skipped: 1, pending: 1 },
};

test("delivery summary counts each canonical status once and matches its total", () => {
  const summary = summarizeDeliveries(deliveries);
  assert.equal(summary.total, 5);
  assert.deepEqual(Object.fromEntries(summary.items.map((item) => [item.status, item.count])), deliveries.summary);
  assert.equal(summary.items.reduce((total, item) => total + item.count, 0), summary.total);
  assert.match(createDeliveryGradient(summary.items, summary.total), /^conic-gradient/);
});

test("duplicate delivery IDs are not counted twice and empty results have no graph", () => {
  const duplicated = { ...deliveries, items: [...deliveries.items, deliveries.items[0]] };
  assert.equal(summarizeDeliveries(duplicated).total, 5);
  assert.equal(summarizeDeliveries({ items: [], summary: { sent: 0, failed: 0, unknown: 0, skipped: 0, pending: 0 } }).total, 0);
  assert.equal(createDeliveryGradient([], 0), "none");
});

test("delivery summary UI reuses one summary for five cards, donut, and two legend columns", async () => {
  const panels = await readFile(new URL("./LowerPanels.tsx", import.meta.url), "utf8");
  const css = await readFile(new URL("./admin.css", import.meta.url), "utf8");
  assert.equal((panels.match(/summarizeDeliveries\(deliveries\)/g) ?? []).length, 1);
  assert.match(panels, /const summary = summarizeDeliveries\(deliveries\)/);
  assert.match(panels, /delivery-summary-cards[^]*summary\.items\.map/);
  assert.match(panels, /createDeliveryGradient\(summary\.items, summary\.total\)/);
  assert.match(panels, /const legendColumns = \[summary\.items\.slice\(0, 3\), summary\.items\.slice\(3\)\]/);
  assert.match(panels, /item\.count \/ summary\.total/);
  assert.match(panels, /toFixed\(1\)/);
  assert.match(panels, /role="img" aria-label=\{`現在のoperationの配信結果、合計\$\{summary\.total\}件`\}/);
  assert.match(css, /delivery-summary-cards\{display:grid;grid-template-columns:repeat\(5,minmax\(0,1fr\)\)/);
  assert.match(css, /delivery-summary-body\{display:grid;grid-template-columns:minmax\(120px,\.75fr\) minmax\(0,1\.75fr\)/);
  assert.match(css, /delivery-legend\{display:grid;grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
  assert.match(css, /@media\(max-width:640px\)[^]*delivery-summary-body\{grid-template-columns:minmax\(0,1fr\)/);
  assert.doesNotMatch(css, /delivery-summary-(?:panel|body)[^}]*overflow/);
});

test("history uses only real timestamps, current operation session events, newest first, and maximum", () => {
  const sessionEvents: SessionHistoryEvent[] = [
    { id: "current", operationId: "OP-A", jobName: "求人A", name: "下書き保存", status: "保存済み", occurredAt: "2026-08-01T04:00:00Z", description: "保存しました。" },
    { id: "other", operationId: "OP-B", jobName: "求人B", name: "下書き保存", status: "保存済み", occurredAt: "2026-08-01T05:00:00Z", description: "別operationです。" },
  ];
  const history = buildOperationHistory(operation(), "求人A", deliveries, sessionEvents, 5);
  assert.equal(history.length, 5);
  assert.equal(history[0].id, "current");
  assert.equal(history.some((item) => item.id === "other"), false);
  assert.equal(history.every((item) => item.operationId === "OP-A"), true);
  assert.equal(history.every((item) => !Number.isNaN(Date.parse(item.occurredAt))), true);
  assert.deepEqual(history.map((item) => Date.parse(item.occurredAt)), [...history].map((item) => Date.parse(item.occurredAt)).sort((a, b) => b - a));
});

test("history has an honest empty state when no operation exists", () => {
  assert.deepEqual(buildOperationHistory(null, null, deliveries, []), []);
});

test("history pagination covers 0, 1, 5, 6, 10, and 11 items without mutating source", () => {
  for (const [count, pages] of [[0, 1], [1, 1], [5, 1], [6, 2], [10, 2], [11, 3]] as const) {
    const source = Array.from({ length: count }, (_, index) => ({ id: `H${index + 1}` }));
    const original = structuredClone(source);
    const result = paginateHistory(source, pages, 5);
    assert.equal(result.totalPages, pages);
    assert.ok(result.pageItems.length <= 5);
    assert.deepEqual(source, original);
  }
  const six = Array.from({ length: 6 }, (_, index) => index + 1);
  assert.deepEqual(paginateHistory(six, 1).pageItems, [1, 2, 3, 4, 5]);
  assert.deepEqual(paginateHistory(six, 2).pageItems, [6]);
  assert.equal(paginateHistory(Array.from({ length: 11 }), 99).currentPage, 3);
});

test("history pagination safely detects additions and clamps a page after shrink", () => {
  assert.equal(containsNewHistory(["H1", "H2"], ["H3", "H1", "H2"]), true);
  assert.equal(containsNewHistory(["H1", "H2"], ["H1", "H2"]), false);
  assert.equal(containsNewHistory([], ["H1"]), false);
  const shrunk = paginateHistory(["H1", "H2"], 3);
  assert.equal(shrunk.currentPage, 1);
  assert.deepEqual(shrunk.pageItems, ["H1", "H2"]);
});

test("recent history renders compact rows and local pagination without API activity", async () => {
  const panels = await readFile(new URL("./LowerPanels.tsx", import.meta.url), "utf8");
  const css = await readFile(new URL("./admin.css", import.meta.url), "utf8");
  assert.match(panels, /const \[page, setPage\] = useState\(1\)/);
  assert.match(panels, /buildOperationHistory\([^]*Number\.MAX_SAFE_INTEGER\)/);
  assert.match(panels, /paginateHistory\(history, requestedPage\)/);
  assert.match(panels, /operationChanged \|\| historyAdded/);
  assert.match(panels, /className="recent-history-row"/);
  assert.match(panels, /formatTime\(item\.occurredAt\)/);
  assert.match(panels, /className="recent-history-icon" aria-hidden="true"/);
  assert.match(panels, /className="recent-history-actor">—/);
  assert.match(panels, /pagination\.showPagination/);
  assert.match(panels, /aria-current=\{pageNumber === pagination\.currentPage \? "page" : undefined\}/);
  assert.doesNotMatch(panels, /fetch\(|adminApi\.|localStorage|sessionStorage|<thead/);
  assert.match(css, /recent-history-row\{display:grid;grid-template-columns:minmax\(44px,auto\) 24px minmax\(78px,auto\) minmax\(0,1fr\) minmax\(30px,auto\)/);
  assert.doesNotMatch(css, /recent-history-row[^}]*box-shadow|recent-history-row[^}]*position:absolute/);
});

test("page scopes deliveries to the current operation and lower panels expose no member identifiers", async () => {
  const page = await readFile(new URL("./page.tsx", import.meta.url), "utf8");
  const panels = await readFile(new URL("./LowerPanels.tsx", import.meta.url), "utf8");
  assert.match(page, /deliveriesOperationId === operation\.operation_id/);
  assert.match(page, /setDeliveriesOperationId\(null\); setSessionHistory\(\[\]\)/);
  assert.match(page, /<DeliverySummaryPanel operation=\{operation\} deliveries=\{currentDeliveries\}/);
  assert.match(page, /<RecentOperationHistory operation=\{operation\}/);
  assert.doesNotMatch(panels, /member_id|provider_request_id|reason_code/);
  assert.doesNotMatch(panels, /現在のoperationと、この画面を開いている間に確認できた操作だけを表示します。正式な監査履歴ではありません。/);
  assert.match(panels, /自動再送は行われません/);
});

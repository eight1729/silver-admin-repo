import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import React from "react";
import * as ordering from "./automatic-workflow.ts";
import * as capability from "./send-capability.ts";
import * as uiState from "./notification-ui-state.ts";
import * as templates from "./notification-templates.ts";

const require = createRequire(import.meta.url);
const flush = () => new Promise<void>(resolve => setImmediate(resolve));
function harness({ failTargets = false, restored = false, zero = false } = {}) {
  const states: any[] = [], refs: any[] = [], effects: any[] = [];
  let stateIndex = 0, refIndex = 0, effectIndex = 0;
  let queued: (() => void)[] = [];
  const calls: string[] = [];
  const storage = new Map<string, string>(restored ? [[ordering.AUTO_OPERATION_KEY, "op-1"]] : []);
  const job = { job_id: "JOB-1", title: "架空の求人", description: "架空の説明", status: "published", summary: null, job_url: "" };
  const rows = ["a", "b"].map((id, i) => ({ member_id: id, member_number: String(i+1), display_name: "架空会員", recommendation_level: 5,
    line_linked: true, eligible: true, reason: null, selected: false }));
  let op: any = { operation_id: "op-1", job_id: "JOB-1", automatic_selection: true, status: "draft", notification_type: "new_job_match",
    target_count: restored ? 2 : 0, selected_member_ids: restored ? ["b", "a"] : [], selected_count: restored ? 2 : 0,
    message: { greeting: "hello", introduction: "job", note: "note" }, send_requested_at: null };
  const cap = { mode: "production_live", ready: true, live_send_enabled: true, max_recipients: null, message_prefix: null };
  const api = {
    jobs: async () => [job], lineSendMode: async () => cap,
    job: async () => job, candidates: async () => rows,
    automaticSelection: async () => ({ selected_member_ids: zero ? [] : ["b", "a"], reason: zero ? "対象0人" : null }),
    createOperation: async (body: any) => { calls.push("create"); assert.equal(body.automatic_selection, true); op.message = body; return op; },
    operation: async () => op,
    updateTargets: async (_id: string, ids: string[]) => {
      calls.push("targets"); if (failTargets) { failTargets = false; throw new Error("offline"); }
      op = { ...op, selected_member_ids: ids, target_count: 2, selected_count: ids.length }; return op;
    },
    updateOperation: async (_id: string, body: any) => { calls.push("message"); op = { ...op, message: body }; return op; },
    validate: async () => { calls.push("validate"); op = { ...op, status: "ready" }; return {}; },
    confirmation: async () => ({ operation_id: "op-1", initial_count: 2, selected_count: 2, sendable_count: 2, excluded_count: 0,
      message: op.message, confirmation_token: "t".repeat(64), can_send: true, requires_revalidation: false, selected_recipient_limit: null,
      targets: rows.map(row => ({ ...row, disposition: "send", mobile_phone_last4: "4321" })) }),
    notificationLink: async () => ({ url: "https://example.invalid/job" }),
    send: async (_id: string, token: string) => { calls.push("send"); assert.equal(token, "t".repeat(64)); op = { ...op, send_requested_at: "now" }; return op; },
    deliveries: async () => ({ items: [], summary: {} }),
  };
  const mocks: Record<string, any> = {
    react: { ...React,
      useState: (initial: any) => { const i = stateIndex++; if (!(i in states)) states[i] = typeof initial === "function" ? initial() : initial;
        return [states[i], (value: any) => { states[i] = typeof value === "function" ? value(states[i]) : value; }]; },
      useRef: (initial: any) => refs[refIndex] ?? (refs[refIndex++] = { current: initial }),
      useEffect: (fn: () => void, deps: any[]) => { const i = effectIndex++, old = effects[i];
        if (!old || deps.some((d, index) => d !== old[index])) { effects[i] = deps; queued.push(fn); } },
    },
    "../lib/admin-api": { adminApi: api, adminErrorMessage: () => "取得失敗" },
    "./JobsNavigationGuard": { JobsNavigationGuard: "guard" }, "./notification-ui-state": uiState,
    "./AdminRouteFrame": { AdminRouteFrame: "frame" }, "./LoadingOverlay": { LoadingOverlay: "loading" },
    "./LowerPanels": { DeliverySummaryPanel: "results" },
    "./MajorPanels": { JobSelectionPanel: "jobs", CandidateSelectionPanel: "members", MessageEditorPanel: "editor" },
    "../components/Modal": { Modal: "modal" },
    "./automatic-workflow": ordering, "./send-capability": capability, "./notification-templates": templates,
  };
  // Refs advance on every render, including already-existing refs.
  mocks.react.useRef = (initial: any) => { const i = refIndex++; return refs[i] ?? (refs[i] = { current: initial }); };
  const module = { exports: {} as any };
  const source = readFileSync(new URL("./AutomaticNotification.tsx", import.meta.url), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020 } }).outputText;
  runInNewContext(code, { module, exports: module.exports, AbortController, Set,
    require: (id: string) => mocks[id] ?? require(id),
    sessionStorage: { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value) },
  });
  const render = () => { stateIndex = 0; refIndex = 0; effectIndex = 0;
    const tree = module.exports.AutomaticNotification({ initialJobId: null });
    const pending = queued; queued = []; pending.forEach(fn => fn()); return tree; };
  return { render, calls, storage };
}

function find(node: any, predicate: (value: any) => boolean): any {
  if (!node) return undefined;
  if (Array.isArray(node)) { for (const child of node) { const result = find(child, predicate); if (result) return result; } return undefined; }
  if (typeof node !== "object") return undefined;
  if (predicate(node)) return node;
  return find(node.props?.children, predicate) ?? find(node.props?.footer, predicate);
}

test("automatic screen saves standard draft and validates but sends only from final button; double click is fenced", async () => {
  const h = harness(); h.render(); await flush();
  const choose = find(h.render(), node => node.type === "jobs").props.select;
  await Promise.all([choose("JOB-1"), choose("JOB-1")]);
  assert.deepEqual(h.calls, ["create", "targets", "message", "validate"]);
  const confirm = find(h.render(), node => node.type === "modal");
  assert.ok(confirm);
  assert.deepEqual([...h.storage.entries()], [[ordering.AUTO_OPERATION_KEY, "op-1"]]);
  const button = find(confirm, node => node.type === "button" && node.props.children === "送信");
  assert.equal(button.props.disabled, false);
  button.props.onClick(); button.props.onClick(); await flush();
  assert.equal(h.calls.filter(call => call === "send").length, 1);
});

test("target-save failure retries the same operation and reload never restores a send token", async () => {
  const h = harness({ failTargets: true }); h.render(); await flush();
  await find(h.render(), node => node.type === "jobs").props.select("JOB-1");
  assert.deepEqual(h.calls, ["create", "targets"]);
  await find(h.render(), node => node.type === "members").props.begin();
  assert.deepEqual(h.calls, ["create", "targets", "targets", "message", "validate"]);
  const restored = harness({ restored: true }); restored.render(); await flush();
  const tree = restored.render();
  assert.ok(find(tree, node => node.type === "editor"));
  assert.equal(find(tree, node => node.type === "modal"), undefined);
  assert.deepEqual(restored.calls, []);
});

test("zero automatic targets stays at job selection without manual target editing or an operation", async () => {
  const h = harness({ zero: true }); h.render(); await flush();
  await find(h.render(), node => node.type === "jobs").props.select("JOB-1");
  const tree = h.render();
  assert.ok(find(tree, node => node.type === "jobs"));
  assert.equal(find(tree, node => node.type === "members"), undefined);
  assert.deepEqual(h.calls, []);
  assert.equal(h.storage.size, 0);
});

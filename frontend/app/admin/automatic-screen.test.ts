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
import * as notificationReasons from "./notification-reasons.ts";
import * as notificationText from "./notification-text.ts";
import * as templates from "./notification-templates.ts";

const require = createRequire(import.meta.url);
const flush = () => new Promise<void>(resolve => setImmediate(resolve));
function harness({ failTargets = false, restored = false, zero = false, stale = false, completed = false,
  accepted = false, failCandidates = false, failResults = false, excludedMember = false,
  failMessage = false, failValidation = false, lostTargetsResponse = false } = {}) {
  const states: any[] = [], refs: any[] = [], effects: any[] = [];
  let stateIndex = 0, refIndex = 0, effectIndex = 0;
  let queued: (() => void)[] = [];
  const calls: string[] = [], locations: string[] = [], urls: string[] = [];
  const storage = new Map<string, string>((restored || stale) ? [[ordering.AUTO_OPERATION_KEY, "op-1"]] : []);
  const job = { job_id: "JOB-1", title: "架空の求人", description: "架空の説明", status: "published", summary: null, job_url: "" };
  const rows = ["a", "b"].map((id, i) => ({ member_id: id, member_number: String(i+1), display_name: "架空会員", recommendation_level: 5,
    line_linked: true, eligible: true, reason: null, selected: false }));
  let op: any = { operation_id: "op-1", job_id: "JOB-1", automatic_selection: true, status: completed ? "completed" : "draft", notification_type: "new_job_match",
    target_count: restored ? 2 : 0, selected_member_ids: restored ? ["b", "a"] : [], selected_count: restored ? 2 : 0,
    updated_at: "before", message: { greeting: "hello", introduction: "job", note: "note" }, send_requested_at: completed || accepted ? "now" : null };
  const excludedIds = new Set(excludedMember ? ["a"] : []);
  const reincludes: string[][] = [];
  const cap = { mode: "production_live", ready: true, live_send_enabled: true, max_recipients: null, message_prefix: null };
  const api = {
    jobs: async () => [job], lineSendMode: async () => cap,
    job: async () => job, candidates: async () => { if (failCandidates) throw Error("candidate outage"); return rows; },
    automaticSelection: async () => ({ selected_member_ids: zero ? [] : ["b", "a"], reason: zero ? "対象0人" : null }),
    createOperation: async (body: any) => { calls.push("create"); assert.equal(body.automatic_selection, true); op.message = body; return op; },
    operation: async () => op,
    updateTargets: async (_id: string, ids: string[], explicit: string[]) => {
      reincludes.push(Array.from(explicit));
      calls.push("targets"); if (failTargets) { failTargets = false; throw new Error("offline"); }
      if (explicit.some(id => !excludedIds.has(id) || !ids.includes(id))) throw Error("invalid explicit re-selection");
      explicit.forEach(id => excludedIds.delete(id));
      op = { ...op, updated_at: "targets-saved", selected_member_ids: ids, target_count: 2, selected_count: ids.length };
      if (lostTargetsResponse) { lostTargetsResponse = false; throw Error("response lost"); } return op;
    },
    updateOperation: async (_id: string, body: any) => { calls.push("message"); if (failMessage) { failMessage = false; throw Error("message failed"); } op = { ...op, message: body }; return op; },
    validate: async () => { calls.push("validate"); if (failValidation) { failValidation = false; throw Error("validation failed"); } op = { ...op, status: "ready" }; return {}; },
    confirmation: async () => ({ operation_id: "op-1", initial_count: 2, selected_count: op.selected_count, sendable_count: op.selected_count - excludedIds.size, excluded_count: excludedIds.size,
      message: op.message, confirmation_token: "t".repeat(64), can_send: true, requires_revalidation: false, selected_recipient_limit: null,
      targets: rows.filter(row => op.selected_member_ids.includes(row.member_id)).map(row => ({ ...row, disposition: excludedIds.has(row.member_id) ? "skip" : "send", mobile_phone_last4: "4321" })) }),
    notificationLink: async () => ({ url: "https://example.invalid/job" }),
    send: async (_id: string, token: string) => { calls.push("send"); assert.equal(token, "t".repeat(64)); op = { ...op, send_requested_at: "now" }; return op; },
    deliveries: async () => { if (failResults) throw Error("results failed"); return { items: [{ member_id: "a", status: completed ? "sent" : "pending" }], summary: {} }; },
  };
  const mocks: Record<string, any> = {
    "./notification-reasons": notificationReasons,
    "./notification-text": notificationText,
    react: { ...React,
      useState: (initial: any) => { const i = stateIndex++; if (!(i in states)) states[i] = typeof initial === "function" ? initial() : initial;
        return [states[i], (value: any) => { states[i] = typeof value === "function" ? value(states[i]) : value; }]; },
      useRef: (initial: any) => refs[refIndex] ?? (refs[refIndex++] = { current: initial }),
      useEffect: (fn: () => void, deps: any[]) => { const i = effectIndex++, old = effects[i];
        if (!old || deps.some((d, index) => d !== old[index])) { effects[i] = deps; queued.push(fn); } },
    },
    "../lib/admin-api": { adminApi: api, adminErrorMessage: () => "取得失敗" },
    "./use-loading-tasks": { useLoadingTasks: () => ({ status: null, track: (_label: string, action: () => Promise<unknown>) => action() }) },
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
    window: { history: { replaceState: (_s: any, _t: any, url: string) => urls.push(url) }, location: { assign: (url: string) => locations.push(url) } },
    require: (id: string) => mocks[id] ?? require(id),
    sessionStorage: { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value) },
  });
  const render = () => { stateIndex = 0; refIndex = 0; effectIndex = 0;
    const tree = module.exports.AutomaticNotification({ initialJobId: null, resumeOperationId: restored ? "op-1" : null });
    const pending = queued; queued = []; pending.forEach(fn => fn()); return tree; };
  return { render, calls, storage, locations, urls, reincludes, api, changeOperation: (change: any) => { op = { ...op, ...change }; } };
}

test("lost response blocks target replay until reconciliation succeeds, and never restores its token", async () => {
  const h = harness({ restored: true, excludedMember: true, lostTargetsResponse: true });
  await reselect(h);
  const operation = h.api.operation;
  h.api.operation = async () => { throw Error("read outage"); };
  await find(h.render(), n => n.type === "members").props.begin();
  await find(h.render(), n => n.type === "members").props.begin();
  assert.equal(h.reincludes.length, 1);
  assert.equal(find(h.render(), n => n.type === "modal"), undefined);
  h.api.operation = operation;
  await find(h.render(), n => n.type === "members").props.begin();
  assert.equal(h.reincludes.length, 1); // Recovery requires a fresh review action.
  assert.equal(find(h.render(), n => n.type === "modal"), undefined);
  await find(h.render(), n => n.type === "members").props.begin();
  assert.deepEqual(h.reincludes, [["a"], []]);
  assert.ok(find(h.render(), n => n.type === "modal"));
});

test("concurrent target change after a lost response replaces stale selection and does not report save success", async () => {
  const h = harness({ restored: true, excludedMember: true, lostTargetsResponse: true });
  await reselect(h);
  const updateTargets = h.api.updateTargets;
  h.api.updateTargets = async (...args) => {
    try { return await updateTargets(...args); }
    finally { h.changeOperation({ selected_member_ids: ["b"], selected_count: 1, updated_at: "concurrent" }); }
  };
  const oldAction = find(h.render(), n => n.type === "members").props.begin;
  await oldAction();
  assert.deepEqual([...find(h.render(), n => n.type === "members").props.selected], ["b"]);
  assert.equal(find(h.render(), n => n.type === "modal"), undefined);
  await oldAction();
  assert.equal(h.reincludes.length, 1);
  assert.equal(h.calls.includes("message"), false);
});

test("an exclusion stays excluded without explicit re-selection and stale selection handlers cannot save", async () => {
  const h = harness({ restored: true, excludedMember: true });
  h.render(); await flush();
  find(h.render(), n => n.type === "button" && n.props.children === "会員を選択").props.onClick();
  const stale = find(h.render(), n => n.type === "members").props.begin;
  find(h.render(), n => n.type === "members").props.toggle("b");
  await stale(); assert.deepEqual(h.calls, []);
  await find(h.render(), n => n.type === "members").props.begin();
  assert.deepEqual(h.reincludes, [[]]);
  assert.match(JSON.stringify(find(h.render(), n => n.type === "modal")), /除外/);
  const view = await h.api.confirmation();
  assert.equal(view.targets.find(t => t.member_id === "a")?.disposition, "skip");
});

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
  assert.equal(find(h.render(), node => node.type === "modal"), undefined);
  const editor = find(h.render(), node => node.type === "editor");
  assert.ok(templates.hasUnfilledNotificationFields(editor.props.message));
  await fillTemplate(h);
  const confirm = find(h.render(), node => node.type === "modal");
  assert.ok(confirm);
  assert.equal(confirm.props.placement, "center");
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


test("previous stored operation cannot contaminate new automatic work or restore its confirmation", async () => {
  const h = harness({ stale: true }); h.render(); await flush();
  assert.ok(find(h.render(), n => n.type === "jobs"));
  assert.equal(find(h.render(), n => n.type === "results"), undefined);
  await find(h.render(), n => n.type === "jobs").props.select("JOB-1");
  assert.deepEqual(h.calls, ["create", "targets", "message", "validate"]);
  assert.ok(h.urls.some(url => url.includes("operationId=op-1")));
});

test("completed automatic results start a fresh job-list handoff without mutating or deleting old work", async () => {
  const h = harness({ restored: true, completed: true }); h.render(); await flush(); h.render(); await flush();
  const button = find(h.render(), n => n.type === "button" && n.props.children === "求人を変更して新規作成");
  assert.equal(button.props.disabled, false); button.props.onClick();
  assert.deepEqual(h.locations, ["/admin/jobs"]); assert.deepEqual(h.calls, []);
  assert.equal(h.storage.get(ordering.AUTO_OPERATION_KEY), "op-1");
});

test("accepted but incomplete send does not allow changing job through the result action", async () => {
  const h = harness(); h.render(); await flush();
  await find(h.render(), n => n.type === "jobs").props.select("JOB-1");
  await fillTemplate(h);
  find(h.render(), n => n.type === "button" && n.props.children === "送信").props.onClick();await flush();h.render();await flush();
  const button=find(h.render(), n => n.type === "button" && n.props.children === "求人を変更して新規作成");
  assert.equal(button.props.disabled, true);button.props.onClick();assert.deepEqual(h.locations, []);
});

for (const completed of [true, false]) test(`resume ${completed ? "completed" : "accepted"} operation despite candidate outage`, async () => {
  const h = harness({ restored: true, completed, accepted: true, failCandidates: true });
  h.render(); await flush(); h.render(); await flush();
  const tree = h.render(), result = find(tree, n => n.type === "results");
  assert.ok(result); assert.equal(result.props.deliveries.items[0].status, completed ? "sent" : "pending");
  assert.equal(find(tree, n => n.type === "modal"), undefined);
  assert.equal(find(tree, n => n.type === "editor"), undefined);
  assert.deepEqual(h.calls, []);
});

test("unsent candidate outage remains an error and result failure stays explicitly retryable", async () => {
  const draft = harness({ restored: true, failCandidates: true }); draft.render(); await flush();
  assert.ok(find(draft.render(), n => n.props.role === "alert"));
  assert.equal(find(draft.render(), n => n.type === "results"), undefined);
  const sent = harness({ restored: true, completed: true, failCandidates: true, failResults: true });
  sent.render(); await flush(); sent.render(); await flush();
  assert.equal(find(sent.render(), n => n.type === "results").props.error, "取得失敗");
  assert.deepEqual(sent.calls, []);
});

async function reselect(h: ReturnType<typeof harness>) {
  h.render(); await flush();
  find(h.render(), n => n.type === "button" && n.props.children === "会員を選択").props.onClick();
  find(h.render(), n => n.type === "members").props.toggle("a");
  find(h.render(), n => n.type === "members").props.toggle("a");
}
for (const failure of ["failMessage", "failValidation", "lostTargetsResponse", "failTargets"] as const) {
  test(`explicit re-selection safely retries after ${failure}`, async () => {
    const h = harness({ restored: true, excludedMember: true, [failure]: true });
    await reselect(h);
    const firstAction = find(h.render(), n => n.type === "members").props.begin;
    await firstAction();
    assert.equal(find(h.render(), n => n.type === "modal"), undefined);
    if (failure !== "failTargets") {
      await firstAction();
      assert.equal(h.reincludes.length, 1); // A stale handler must not replay consumed intent.
    }
    await find(h.render(), n => n.type === "members").props.begin();
    assert.ok(find(h.render(), n => n.type === "modal"));
    assert.deepEqual(h.reincludes, [["a"], failure === "failTargets" ? ["a"] : []]);
    assert.equal(h.calls.includes("send"), false);
  });
}

for (const status of ["sending", "completed", "completed_with_errors"]) test(`durable ${status} status restores results without a timestamp or editing dependencies`, async () => {
  const h = harness({ restored: true }); h.changeOperation({ status, send_requested_at: null });
  h.api.jobs = h.api.job = h.api.candidates = h.api.confirmation = h.api.lineSendMode = async () => { throw Error("editing dependency unavailable"); };
  h.render(); await flush(); h.render(); await flush();
  const result = find(h.render(), n => n.type === "results");
  assert.ok(result); assert.equal(result.props.operation.status, status); assert.equal(result.props.error, "");
  assert.deepEqual(h.calls, []);
});

test("result retry converges from waiting to completed using reads only", async () => {
  const h = harness({ restored: true, accepted: true, failCandidates: true, failResults: true });
  h.render(); await flush(); h.render(); await flush();
  assert.equal(find(h.render(), n => n.type === "results").props.error, "取得失敗");
  h.changeOperation({ status: "completed" });
  h.api.deliveries = async () => ({ items: [{ member_id: "a", status: "sent" }], summary: {} });
  await find(h.render(), n => n.type === "results").props.retry();
  const result = find(h.render(), n => n.type === "results");
  assert.equal(result.props.error, ""); assert.equal(result.props.operation.status, "completed");
  assert.equal(result.props.deliveries.items[0].status, "sent"); assert.deepEqual(h.calls, []);
});


async function fillTemplate(h: ReturnType<typeof harness>) {
  const editor = find(h.render(), n => n.type === "editor");
  editor.props.setMessage({ ...editor.props.message, greeting: editor.props.message.greeting.replace(/【未入力：[^】]+】/g, "架空の入力済み値") });
  await find(h.render(), n => n.type === "button" && n.props.children === "保存・再検証して最終確認へ").props.onClick();
  await flush();
}

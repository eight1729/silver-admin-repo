import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import React from "react";
import ts from "typescript";
import * as entryUrls from "./automatic-workflow.ts";

const require = createRequire(import.meta.url);
const flush = () => new Promise<void>(resolve => setImmediate(resolve));
const read = (file: string) => readFileSync(new URL(file, import.meta.url), "utf8");
function harness(file: string, name: string, mocks: any = {}, globals: any = {}) {
  const states: any[] = [], refs: any[] = [], deps: any[] = [], cleanups: any[] = [];
  let si = 0, ri = 0, ei = 0, updates = 0;
  let queue: any[] = [];
  const hooks = { ...React,
    useState: (initial: any) => { const i = si++; if (!(i in states)) states[i] = typeof initial === "function" ? initial() : initial;
      return [states[i], (value: any) => { updates++; states[i] = typeof value === "function" ? value(states[i]) : value; }]; },
    useRef: (value: any) => { const i = ri++; return refs[i] ?? (refs[i] = { current: value }); },
    useCallback: (fn: any) => fn,
    useEffect: (fn: any, values: any[]) => { const i = ei++; if (!deps[i] || values.some((v, j) => v !== deps[i][j])) {
      deps[i] = values; queue.push(() => { cleanups[i]?.(); cleanups[i] = fn(); }); } },
  };
  const module = { exports: {} as any };
  runInNewContext(ts.transpileModule(read(file), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
  } }).outputText, { module, exports: module.exports, AbortController, URLSearchParams, ...globals,
    require: (id: string) => id === "react" ? hooks : mocks[id] ?? require(id) });
  return {
    render(props: any = {}) { si = ri = ei = 0; const result = module.exports[name](props); const pending = queue; queue = []; pending.forEach(fn => fn()); return result; },
    unmount() { cleanups.forEach(fn => fn?.()); }, get updates() { return updates; },
  };
}
function deferred() {
  let resolve!: (value?: any) => void, reject!: (reason: unknown) => void;
  const promise = new Promise<any>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

test("overlapping loading tasks retain the active label through old completion, failure, cancellation and unmount", async () => {
  const h = harness("./use-loading-tasks.ts", "useLoadingTasks");
  const { track } = h.render();
  const first = deferred(), second = deferred();
  const a = track("求人一覧を取得中…", () => first.promise);
  const b = track("対象会員を保存中…", () => second.promise);
  assert.equal(h.render().status, "対象会員を保存中…");
  first.resolve(); await a;
  assert.equal(h.render().status, "対象会員を保存中…");
  second.reject(new Error("offline")); await assert.rejects(b);
  assert.equal(h.render().status, null);
  const slow = deferred(), fast = deferred();
  const c = track("候補会員を取得中…", () => slow.promise);
  const d = track("求人詳細を取得中…", () => fast.promise);
  fast.reject(new DOMException("cancelled", "AbortError")); await assert.rejects(d);
  assert.equal(h.render().status, "候補会員を取得中…");
  h.unmount(); const updates = h.updates; slow.resolve(); await c;
  assert.equal(h.updates, updates);
});

function entryHarness(search: string, automatic = true, fail = false) {
  const calls: string[] = [], urls: string[] = [];
  const h = harness("./NotificationEntry.tsx", "NotificationEntry", {
    "./automatic-workflow": entryUrls,
    "./SelectionModeDialog": { SelectionModeDialog: "picker" },
    "./AutomaticNotification": { AutomaticNotification: "automatic" },
    "./LoadingOverlay": { LoadingOverlay: "loading" },
    "../lib/admin-api": { adminErrorMessage: () => "再開失敗", adminApi: { operation: async (id: string) => {
      calls.push(id); if (fail) throw Error("offline"); return { automatic_selection: automatic }; } } },
  }, { window: { location: { search }, history: { replaceState: (_s: any, _t: any, url: string) => urls.push(url) } },
    sessionStorage: { getItem: () => { throw Error("Implicit previous operation access is forbidden"); } } });
  return { ...h, calls, urls, render: () => h.render({ manual: (jobId: string | null, operationId: string | null) => ({ type: "manual", props: { jobId, operationId } }) }) };
}
function picker(tree: any): any { return tree.props.children.find((node: any) => node?.type === "picker"); }

test("ordinary /admin starts at the picker without reading previous operation or delivery; handoff is fresh", async () => {
  const h = entryHarness(""); h.render(); await flush();
  picker(h.render()).props.choose("auto");
  assert.equal(h.render().props.resumeOperationId, null);
  assert.deepEqual(h.calls, []); assert.deepEqual(h.urls, ["/admin?mode=auto"]);
  const job = entryHarness("?mode=auto&jobId=JOB-1"); job.render(); await flush();
  assert.equal(job.render().props.initialJobId, "JOB-1"); assert.equal(job.render().props.resumeOperationId, null);
});

test("explicit operation URL and reload use saved mode and identity, not a stale mode query; invalid resume never restores", async () => {
  const id = "11111111-1111-4111-8111-111111111111";
  const url = entryUrls.notificationEntryUrl("manual", null, id);
  for (const automatic of [true, false]) {
    for (let reload = 0; reload < 2; reload++) {
      const h = entryHarness(url.slice(url.indexOf("?")), automatic); h.render(); await flush();
      const result = h.render(); assert.equal(result.type, automatic ? "automatic" : "manual");
      assert.equal(automatic ? result.props.resumeOperationId : result.props.operationId, id);
      assert.deepEqual(h.calls, [id]);
    }
  }
  for (const query of ["?operationId=bad", `?operationId=${id}&operationId=${id}`]) {
    const h = entryHarness(query); h.render(); await flush(); assert.ok(picker(h.render())); assert.deepEqual(h.calls, []);
  }
  const failed = entryHarness(`?operationId=${id}`, true, true); failed.render(); await flush(); assert.ok(picker(failed.render()));
});

test("manual resume uses only explicitly selected operation and its saved targets; fresh create cannot use old storage as success", () => {
  const manual = read("./page.tsx");
  assert.match(manual, /const saved = resumeOperationId/);
  assert.match(manual, /saved && sessionStorage.getItem\(STORAGE_KEY\) === saved/);
  assert.match(manual, /op.selected_member_ids \?\? \[\]/);
  assert.match(manual, /if \(savedOperation\)/);
  assert.match(manual, /notificationEntryUrl\("manual", null, operation.operation_id\)/);
  assert.match(read("./AutomaticNotification.tsx"), /notificationEntryUrl\("auto", null, value.operation_id\)/);
  const modal = read("../components/Modal.tsx");
  assert.match(modal, /maxHeight: "90vh"/); assert.match(modal, /overflowY: "auto"/);
  assert.match(modal, /e.key === "Escape"/); assert.match(modal, /e.key === "Tab"/);
});

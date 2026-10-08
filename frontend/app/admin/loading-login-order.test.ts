import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import test from "node:test";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { orderCandidates } from "./candidate-order.ts";

const require = createRequire(import.meta.url);
const read = (name: string) => readFileSync(new URL(name, import.meta.url), "utf8");
const page = read("./page.tsx");
function compile(source: string, globals: Record<string, any> = {}, mocks: Record<string, any> = {}): any {
  const module = { exports: {} };
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020,
  } }).outputText;
  runInNewContext(code, { module, exports: module.exports, DOMException,
    require: (id: string) => id.endsWith(".css") ? {} : mocks[id] ?? require(id), ...globals });
  return module.exports;
}

test("overlay renders only while active, with spinner, live status and keyboard cleanup", () => {
  let effect: (() => void | (() => void)) | undefined;
  let focused = 0, restored = 0;
  class Element { isConnected = true; focus() { restored++; } }
  const listeners = new Map<string, Function>();
  const component = compile(read("./LoadingOverlay.tsx"), {
    HTMLElement: Element, document: { activeElement: new Element(),
      addEventListener: (key: string, value: Function) => listeners.set(key, value),
      removeEventListener: (key: string) => listeners.delete(key) },
  }, { react: { ...React, useRef: () => ({ current: { focus: () => focused++, contains: () => false } }),
    useEffect: (value: typeof effect) => { effect = value; } } }).LoadingOverlay;
  assert.equal(component({ active: false }), null);
  assert.equal(effect!(), undefined);
  const html = renderToStaticMarkup(component({ active: true }));
  assert.match(html, /Loading\.\.\./);
  assert.match(html, /admin-loading-spinner/);
  assert.match(html, /role="status".*aria-live="polite".*aria-busy="true"/);
  const cleanup = effect!();
  assert.equal(focused, 1);
  let prevented = false;
  listeners.get("keydown")!({ key: "Tab", preventDefault: () => { prevented = true; } });
  assert.equal(prevented, true);
  listeners.get("focusin")!({ target: {} });
  assert.equal(focused, 2);
  assert.equal(typeof cleanup, "function");
  (cleanup as Function)();
  assert.equal(listeners.size, 0);
  assert.equal(restored, 1);
  assert.equal(component({ active: false }), null);
  assert.match(read("./loading-overlay.css"), /position:fixed;inset:0/);
  assert.match(read("./loading-overlay.css"), /pointer-events:auto/);
});

test("login GIS mount stays inside a centered card without an overlay", () => {
  const StaffLogin = compile(read("./StaffLogin.tsx"), { process: { env: { NEXT_PUBLIC_GOOGLE_CLIENT_ID: "public-client" } } }, {
    react: { ...React, useRef: () => ({ current: null }), useState: () => [false, () => {}], useEffect: () => {} },
    "./staff-auth": {},
  }).StaffLogin;
  const html = renderToStaticMarkup(StaffLogin());
  assert.match(html, /class="admin-login-card"[\s\S]*class="admin-login-button"/);
  assert.match(html, /管理画面/);
  assert.doesNotMatch(html, /admin-loading-overlay/);
  assert.match(read("./staff-login.css"), /place-items:center/);
  assert.match(read("./AdminAuthBoundary.tsx"), /state === "unauthenticated"\) return <StaffLogin/);
});

test("display ordering preserves identifiers, ties, missing-number order and input", () => {
  const rows = [{ member_id: "uuid-3", member_number: "0003" }, { member_id: "external-a" },
    { member_id: "uuid-1", member_number: "0001" }, { member_id: "external-b", member_number: null },
    { member_id: "uuid-2", member_number: "0002" }, { member_id: "uuid-tie", member_number: "0001" }];
  const before = [...rows];
  const ordered = orderCandidates(rows);
  assert.deepEqual(ordered.map(r => r.member_id), ["uuid-1", "uuid-tie", "uuid-2", "uuid-3", "external-a", "external-b"]);
  assert.deepEqual(rows, before);
  assert.equal(ordered[0], rows[2]);
  assert.deepEqual(orderCandidates(rows.filter(r => r.member_number == null)).map(r => r.member_id), ["external-a", "external-b"]);
  assert.match(read("./MajorPanels.tsx"), /filterCandidates\(orderCandidates\(candidates\), filter\)/);
  assert.match(read("./members/page.tsx"), /orderCandidates\(candidates\)\.map/);
});

function extract(name: string, next: string) {
  return page.slice(page.indexOf(`  async function ${name}(`), page.indexOf(`  async function ${next}(`));
}
const noop = () => {};
for (const fail of [false, true]) {
  test(`initial jobs loading clears on ${fail ? "failure" : "success"}`, async () => {
    const states: boolean[] = [];
    const start = page.indexOf("  const loadJobs = useCallback(");
    const end = page.indexOf("  }, []);", start);
    const code = page.slice(start, end).replace("useCallback(", "") + "  };\nexports.run = loadJobs;";
    const { run } = compile(code, { setLoading: (v: boolean) => states.push(v), setJobsError: noop,
      clearFeedback: noop, setJobs: noop, showError: noop,
      adminApi: { jobs: async () => { if (fail) throw Error("offline"); return []; } } });
    const pending = run();
    assert.deepEqual(states, [true]);
    await pending;
    assert.deepEqual(states, [true, false]);
  });

  test(`candidate loading clears on ${fail ? "failure" : "success"}`, async () => {
    const states: boolean[] = [];
    const { run } = compile(extract("loadJobAndCandidates", "retryDetail") + "exports.run = loadJobAndCandidates;", {
      jobRequestSequence: { current: 0 }, setBusy: (v: boolean) => states.push(v), clearFeedback: noop,
      setDetailError: noop, setCandidatesError: noop, setJob: noop, setCandidates: noop, showError: noop,
      adminApi: { job: async () => ({}), candidates: async () => { if (fail) throw Error("offline"); return []; } },
    });
    const pending = run("job");
    assert.deepEqual(states, [true]);
    await pending;
    assert.deepEqual(states, [true, false]);
  });

  test(`send lock blocks duplicates and loading clears on ${fail ? "failure" : "success"}`, async () => {
    const states: boolean[] = [];
    let calls = 0, release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const lock = { current: false };
    const { run } = compile(extract("fakeSend", "loadDeliveriesOnly") + "exports.run = fakeSend;", {
      operation: { operation_id: "op" }, workflowState: { canSend: true }, workflowLock: lock,
      setBusy: (v: boolean) => states.push(v), setWorkflowAction: noop, clearFeedback: noop,
      setQueueFailure: noop, setDeliveriesError: noop, setOperation: noop, setStep: noop,
      setDeliveriesLoading: noop, setDeliveries: noop, setDeliveriesOperationId: noop,
      setValidationSnapshot: noop, setValidationInvalidation: noop, setError: noop, showError: noop,
      validationInputRef: { current: { operationId: "op" } }, AdminApiError: class extends Error {},
      adminApi: { operation: async () => ({ operation_id: "op" }) },
      sendThenLoadDeliveries: async () => { calls++; await gate; if (fail) throw Error("offline"); return { deliveries: null }; },
    });
    const pending = run();
    await run();
    assert.equal(calls, 1);
    assert.deepEqual(states, [true]);
    release(); await pending;
    assert.deepEqual(states, [true, false]);
    assert.equal(lock.current, false);
  });
}

test("overlay combines major network states, not polling or local selection", () => {
  assert.match(page, /overlayActive = loading \|\| modeLoading \|\| restoringOperation \|\| busy/);
  assert.match(page, /<LoadingOverlay active=\{overlayActive\}/);
  assert.match(page, /finally\(\(\) => \{ if \(active\) setModeLoading\(false\)/);
  assert.match(page, /finally\(\(\) => \{ if \(active\) setRestoringOperation\(false\)/);
  assert.match(read("./members/page.tsx"), /finally\(\(\) => \{ if \(!controller.signal.aborted\) setLoading\(false\)/);
});


test("cancelled initial request cannot dismiss loading for a newer request", async () => {
  const states: boolean[] = [];
  const start = page.indexOf("  const loadJobs = useCallback(");
  const end = page.indexOf("  }, []);", start);
  const code = page.slice(start, end).replace("useCallback(", "") + "  }; exports.run = loadJobs;";
  const { run } = compile(code, { setLoading: (v: boolean) => states.push(v), setJobsError: noop,
    clearFeedback: noop, setJobs: noop, showError: noop,
    adminApi: { jobs: async () => { throw new DOMException("cancelled", "AbortError"); } } });
  await run({ aborted: true });
  assert.deepEqual(states, [true]);
});

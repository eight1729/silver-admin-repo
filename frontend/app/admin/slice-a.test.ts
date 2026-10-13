import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import React from "react";
import { filterCandidates, memberNumberAtLeast } from "./candidate-filters.ts";
import type { AdminCandidate } from "../lib/admin-api";

const require = createRequire(import.meta.url);
const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
function compile(source: string, mocks: Record<string, any> = {}, globals: Record<string, any> = {}): any {
  const module = { exports: {} };
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020,
  } }).outputText;
  runInNewContext(code, { module, exports: module.exports, AbortController, DOMException,
    require: (id: string) => id.endsWith(".css") ? {} : mocks[id] ?? require(id), ...globals });
  return module.exports;
}

test("root and successful Google login lead to dashboard; notification route stays intact", async () => {
  const redirects: string[] = [];
  compile(read("../../targets/admin/app/page.tsx"), {
    "next/navigation": { redirect: (path: string) => redirects.push(path) },
  }).default();
  let effect: any, accepted: any;
  let failed = false;
  compile(read("./StaffLogin.tsx"), {
    react: { ...React, useRef: () => ({ current: {} }), useState: () => [false, (value: boolean) => { failed = value; }], useEffect: (fn: any) => { effect = fn; } },
    "./staff-auth": { startStaffAuth: () => {}, renderStaffSignIn: async (_element: any, callback: any) => { accepted = callback; } },
  }, { process: { env: { NEXT_PUBLIC_GOOGLE_CLIENT_ID: "public-test-client" } }, window: { location: { replace: (path: string) => redirects.push(path) } } }).StaffLogin();
  const cleanup = effect();
  accepted(false);
  assert.equal(failed, true);
  assert.deepEqual(redirects, ["/admin/dashboard"]);
  accepted(true);
  assert.deepEqual(redirects, ["/admin/dashboard", "/admin/dashboard"]);
  cleanup(); accepted(true);
  assert.equal(redirects.length, 2);
  assert.match(read("../../targets/admin/app/admin/page.tsx"), /export \{ default \} from "\.\.\/\.\.\/\.\.\/\.\.\/app\/admin\/page"/);
});

test("number minimum is precise, inclusive, ANDed, display-preserving and never uses member ID", () => {
  const rows: AdminCandidate[] = ["9", "20", "00100", "9007199254740993", "9007199254740992", null, "", "A100", " 100"].map((number, i) => ({
    member_id: `999999${i}`, member_number: number, display_name: "会員", line_linked: i !== 2,
    eligible: i !== 3, reason: null, selected: i === 0,
  }));
  const before = structuredClone(rows);
  assert.deepEqual(filterCandidates(rows, "all", "100").map(r => r.member_number), ["00100", "9007199254740993", "9007199254740992"]);
  assert.deepEqual(filterCandidates(rows, "line_linked", "100").map(r => r.member_number), ["9007199254740993", "9007199254740992"]);
  assert.deepEqual(filterCandidates(rows, "eligible", "100").map(r => r.member_number), ["00100", "9007199254740992"]);
  assert.deepEqual(filterCandidates(rows, "all", "9007199254740993").map(r => r.member_number), ["9007199254740993"]);
  assert.equal(filterCandidates(rows, "all").length, rows.length);
  assert.deepEqual(filterCandidates(rows, "all", "1e2"), []);
  assert.equal(memberNumberAtLeast("000", "0"), true);
  assert.equal(memberNumberAtLeast("1" + "0".repeat(200), "9".repeat(200)), true);
  for (const invalid of [undefined, null, "", "-1", "+100", "1.5", "１２３", "100\n"]) assert.equal(memberNumberAtLeast(invalid, "0"), false);
  assert.deepEqual(rows, before);
  assert.equal(rows[0].selected, true);
});

function jobsHarness() {
  const values: any[] = [];
  let cursor = 0, effect: any, writes = 0;
  const requests: { signal: AbortSignal; resolve: (value: any[]) => void; reject: (value: unknown) => void }[] = [];
  const ref = { current: null };
  const Page = compile(read("./jobs/page.tsx"), {
    react: { ...React, useRef: () => ref, useEffect: (fn: any) => { effect = fn; }, useState: (initial: any) => {
      const index = cursor++; if (!(index in values)) values[index] = initial;
      return [values[index], (value: any) => { values[index] = value; writes++; }];
    } },
    "../../lib/admin-api": { adminApi: { jobs: (signal: AbortSignal) => new Promise((resolve, reject) => requests.push({ signal, resolve, reject })) }, adminErrorMessage: () => "取得失敗" },
    "../AdminRouteFrame": { AdminRouteFrame: "frame" }, "../LoadingOverlay": { LoadingOverlay: "overlay" }, "../job-status": { jobStatusLabel: () => "公開" },
  }).default;
  const render = () => { cursor = 0; return Page(); };
  render();
  const cleanup = effect();
  return { values, requests, render, cleanup, writes: () => writes };
}
const flush = () => new Promise<void>(resolve => setImmediate(resolve));

test("jobs overlay clears on failure and retry success, retaining the existing error UI", async () => {
  const h = jobsHarness();
  assert.equal(h.render().props.children[0].props.active, true);
  h.requests[0].reject(new Error("offline")); await flush();
  const failed = h.render();
  assert.equal(failed.props.children[0].props.active, false);
  assert.equal(h.values[2], "取得失敗");
  const retry = failed.props.children[2].props.children[1].props.onClick;
  retry();
  assert.equal(h.render().props.children[0].props.active, true);
  assert.equal(h.values[2], "");
  h.requests[1].resolve([]); await flush();
  assert.equal(h.render().props.children[0].props.active, false);
  h.cleanup();
});

test("replaced and unmounted job requests cannot update data, errors or loading", async () => {
  const h = jobsHarness();
  h.requests[0].reject(new Error("offline")); await flush();
  const retry = h.render().props.children[2].props.children[1].props.onClick;
  retry(); retry();
  assert.equal(h.requests[1].signal.aborted, true);
  const before = h.writes();
  h.requests[1].resolve([{ job_id: "stale" }]); await flush();
  assert.equal(h.writes(), before);
  assert.equal(h.values[1], true);
  h.cleanup();
  assert.equal(h.requests[2].signal.aborted, true);
  h.requests[2].reject(new Error("late failure")); await flush();
  assert.equal(h.writes(), before);
});

function sidebarHarness() {
  let blocked = false, observerCallback: any, disconnected = false, closed = 0;
  const listeners = new Map<string, any>();
  const doc: any = { activeElement: null, body: {}, querySelector: () => blocked ? {} : null,
    addEventListener: (name: string, callback: any) => listeners.set(name, callback),
    removeEventListener: (name: string) => listeners.delete(name) };
  const element = () => ({ isConnected: true, focus() { doc.activeElement = this; } });
  const first = element(), last = element(), trigger = element();
  const sidebar = { ...element(), ownerDocument: doc, querySelectorAll: () => [first, last], contains: (el: any) => el === first || el === last || el === sidebar };
  const attach = compile(read("./sidebar-focus.ts"), {}, { MutationObserver: class {
    constructor(callback: any) { observerCallback = callback; }
    observe() {} disconnect() { disconnected = true; }
  } }).attachSidebarFocus;
  const cleanup = attach(sidebar, trigger, () => { closed++; });
  return { doc, first, last, trigger, listeners, cleanup, closeCount: () => closed, disconnected: () => disconnected,
    overlay: () => { blocked = true; observerCallback(); },
    dismissOverlay: () => { blocked = false; observerCallback(); } };
}

test("sidebar traps Tab, closes on Escape and restores trigger focus with cleanup", () => {
  const h = sidebarHarness();
  assert.equal(h.doc.activeElement, h.first);
  let prevented = 0;
  const key = (name: string, shiftKey = false) => h.listeners.get("keydown")({ key: name, shiftKey, preventDefault: () => prevented++ });
  key("Tab", true); assert.equal(h.doc.activeElement, h.last);
  key("Tab"); assert.equal(h.doc.activeElement, h.first);
  h.doc.activeElement = {}; h.listeners.get("focusin")(); assert.equal(h.doc.activeElement, h.first);
  key("Escape"); assert.equal(h.closeCount(), 1); assert.equal(prevented, 3);
  h.cleanup(); assert.equal(h.doc.activeElement, h.trigger);
  assert.equal(h.listeners.size, 0); assert.equal(h.disconnected(), true);
});

test("sidebar yields to Modal or LoadingOverlay without stealing focus on cleanup", () => {
  const h = sidebarHarness();
  const overlay = {}; h.doc.activeElement = overlay;
  h.overlay(); assert.equal(h.closeCount(), 0);
  h.listeners.get("focusin")();
  h.listeners.get("keydown")({ key: "Escape", preventDefault: () => assert.fail("overlay owns Escape") });
  h.cleanup(); assert.equal(h.doc.activeElement, overlay);
});

test("sidebar resumes focus containment after a higher overlay closes", () => {
  const h = sidebarHarness();
  h.overlay(); h.doc.activeElement = {};
  h.dismissOverlay(); assert.equal(h.doc.activeElement, h.first);
  h.cleanup(); assert.equal(h.doc.activeElement, h.trigger);
});

test("sidebar is hidden when closed, overlay width is independent, and PC tables scroll internally", () => {
  const shell = read("./AdminShell.tsx"), css = read("./admin.css"), modal = read("../components/Modal.tsx");
  assert.match(shell, /hidden=\{!menuOpen\}/);
  assert.match(shell, /onClick=\{\(\) => setMenuOpen\(false\)\}/);
  assert.match(css, /\.admin-menu-toggle\{display:inline-grid/);
  assert.match(css, /\.admin-app-body\{display:block/);
  assert.match(css, /\.admin-sidebar\{position:fixed;[^}]*z-index:50/);
  assert.match(css, /\.admin-sidebar\[hidden\]\{display:none\}/);
  assert.match(css, /\.admin-sidebar-backdrop\{position:fixed;[^}]*z-index:40/);
  assert.match(css, /\.candidate-table-wrapper\{overflow:auto/);
  assert.match(modal, /zIndex: 1000/);
  assert.match(modal, /minHeight: 0/);
  assert.match(modal, /flexWrap: "wrap"/);
});

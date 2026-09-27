import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import test from "node:test";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const require = createRequire(import.meta.url);
const source = (name: string) => readFileSync(new URL(name, import.meta.url), "utf8");
// Render actual TSX without booting Next, reading env files, or starting Staff Auth.
function load(name: string, mocks: Record<string, unknown> = {}, globals: Record<string, unknown> = {}) {
  const code = ts.transpileModule(source(name), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020,
  } }).outputText;
  const module = { exports: {} };
  runInNewContext(code, { module, exports: module.exports,
    require: (id: string) => Object.hasOwn(mocks, id) ? mocks[id] : require(id), ...globals });
  return module.exports;
}
const actions = load("./AdminHeaderActions.tsx");
const home = load("./AdminHomeButton.tsx");
const shell = load("./AdminShell.tsx", {
  "next/navigation": { usePathname: () => "/admin" },
  "./notification-templates": { DEFAULT_CENTER_DISPLAY_NAME: "検証用センター" },
  "./send-capability": { modePresentation: () => ({ tone: "blocked", label: "送信不可", detail: "確認してください" }) },
  "./AdminHeaderActions": actions, "./AdminHomeButton": home,
});

function boundary(state: string, required = true, denied: number | null = null) {
  let calls = 0;
  const redirects: string[] = [];
  let hook = 0;
  const component = load("./AdminAuthBoundary.tsx", {
    react: { ...React, useEffect: () => {}, useState: () => [hook++ === 0 ? state : denied, () => {}] },
    "./StaffLogin": { StaffLogin: () => React.createElement("p", null, "ログイン") },
    "./AdminHeaderActions": actions,
    "./staff-auth": { logoutStaff: () => { calls++; } },
  }, { window: { location: { replace: (url: string) => redirects.push(url) } } });
  // VM exports are JS values; validate the expected entrypoints before invocation.
  assert.ok("AdminAuthBoundary" in component && typeof component.AdminAuthBoundary === "function");
  assert.ok("AdminShell" in shell && typeof shell.AdminShell === "function");
  const Shell = shell.AdminShell;
  const element = component.AdminAuthBoundary({ required,
    children: React.createElement(() => Shell({ mode: null, children: "protected page" })),
  });
  return { element, html: renderToStaticMarkup(element), calls: () => calls, redirects };
}

test("authorized Logout renders exactly once inside visible Header, and invokes existing action once", () => {
  const h = boundary("authenticated");
  const header = h.html.match(/<header class="admin-app-header">[\s\S]*?<\/header>/)?.[0];
  assert.ok(header);
  assert.equal((h.html.match(/ログアウト/g) ?? []).length, 1);
  assert.match(header, /admin-header-actions[\s\S]*ログアウト/);
  assert.match(header, /type="button"[^>]*>求人一覧へ戻る/);
  h.element.props.value.props.onClick();
  assert.equal(h.calls(), 1); assert.deepEqual(h.redirects, ["/auth-required"]);
});

test("forbidden retains standalone Logout without protected Header or content", () => {
  const h = boundary("forbidden");
  assert.match(h.html, /この画面を利用する権限がありません/);
  assert.equal((h.html.match(/ログアウト/g) ?? []).length, 1);
  assert.doesNotMatch(h.html, /admin-app-header|protected page/);
  h.element.props.children[2].props.onClick();
  assert.equal(h.calls(), 1); assert.deepEqual(h.redirects, ["/auth-required"]);
});

for (const state of ["loading", "unauthenticated"]) {
  test(`${state} has no protected Header or Logout flash`, () => {
    assert.doesNotMatch(boundary(state).html, /admin-app-header|ログアウト|protected page/);
  });
}

test("auth-disabled mode and its 401/403 screens preserve existing Logout absence", () => {
  assert.match(boundary("loading", false).html, /admin-app-header/);
  assert.doesNotMatch(boundary("loading", false).html, /ログアウト/);
  for (const status of [401, 403]) assert.doesNotMatch(boundary("loading", false, status).html, /admin-app-header|ログアウト|protected page/);
});

for (const [busy, action, expected] of [[false, "idle", "jobs"], [true, "idle", "edit"], [false, "sending", "edit"]] as const) {
  test(`visible Home dispatch preserves page handler: busy=${busy}, action=${action}`, () => {
    const bus = new EventTarget();
    let step = "edit";
    let events = 0;
    const body = source("./page.tsx").match(/const returnToJobs = useCallback\(\(\) => \{([\s\S]*?)\}, \[busy, workflowAction\]\);/)?.[1];
    assert.ok(body);
    const handler = runInNewContext(`() => {${body}}`, { busy, workflowAction: action, setStep: (value: string) => { step = value; } });
    bus.addEventListener("demo-admin:show-jobs", () => { events++; handler(); });
    const loaded = load("./AdminHomeButton.tsx", {}, { window: bus, Event });
    assert.ok("AdminHomeButton" in loaded && typeof loaded.AdminHomeButton === "function");
    loaded.AdminHomeButton().props.onClick();
    assert.equal(events, 1); assert.equal(step, expected);
    assert.match(source("./page.tsx"), /window.addEventListener\(ADMIN_HOME_EVENT, handler\)/);
    assert.match(source("./page.tsx"), /window.removeEventListener\(ADMIN_HOME_EVENT, handler\)/);
  });
}

test("legacy hidden controls and dedicated CSS are retired; Home stays scoped to its handler route", () => {
  assert.doesNotMatch(source("./layout.tsx"), /admin-legacy-header|AdminHomeButton|aria-hidden/);
  const css = source("./admin.css");
  assert.doesNotMatch(css, /\.admin-legacy-header|\.admin-header[\s{.]|\.admin-kicker|\.admin-home-link/);
  assert.match(source("./AdminShell.tsx"), /pathname === "\/admin" && <AdminHomeButton/);
  assert.doesNotMatch(boundary("authenticated").html.match(/<header[\s\S]*?<\/header>/)![0], /<(?:header|div)[^>]*aria-hidden="true"/);
});

test("Header actions wrap at narrow widths and retain keyboard button focus styling", () => {
  const css = source("./admin.css");
  assert.match(css, /\.admin-app-header\{[^}]*flex-wrap:wrap/);
  assert.match(css, /\.admin-header-actions\{[^}]*flex-wrap:wrap[^}]*max-width:100%/);
  assert.match(css, /@media\(max-width:760px\)\{[^}]*\}\s*\.admin-header-actions\{width:100%\}/);
  assert.match(css, /\.admin-button:focus-visible[^}]*outline:3px/);
});

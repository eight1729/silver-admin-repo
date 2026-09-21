import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { test } from "node:test";
import ts from "typescript";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const key = "admin_staff_id_token";
const now = 2_000_000_000_000;
// Deliberately unsigned: the frontend uses exp for UX, never as proof of identity.
const credential = (exp = now / 1000 + 60) => `header.${Buffer.from(JSON.stringify({ exp })).toString("base64url")}.signature`;

function browser(saved?: string) {
  const storage = new Map(saved ? [[key, saved]] : []);
  const events = new EventTarget();
  const timers = new Map<number, () => void>();
  let clock = now;
  let timerId = 0;
  let cookie = "";
  let status = 200;
  let requestHeaders: Record<string, string> = {};
  let options: any;
  let rendered = 0;
  let disabled = 0;
  const identity = {
    initialize: (value: unknown) => { options = value; },
    renderButton: () => { rendered++; },
    disableAutoSelect: () => { disabled++; },
  };
  const window = Object.assign(events, { google: { accounts: { id: identity } } });
  const document = {
    get cookie() { return cookie; },
    set cookie(value) { cookie = value; },
  };
  const context = vm.createContext({
    window, document, location: { protocol: "https:" },
    sessionStorage: { getItem: (k: string) => storage.get(k) ?? null, setItem: (k: string, v: string) => storage.set(k, v), removeItem: (k: string) => storage.delete(k) },
    Date: { now: () => clock }, atob, CustomEvent, DOMException,
    setTimeout: (callback: () => void) => { timers.set(++timerId, callback); return timerId; },
    clearTimeout: (id: number) => timers.delete(id),
    process: { env: { NEXT_PUBLIC_ADMIN_API_BASE_URL: "https://admin-api.example.test", NEXT_PUBLIC_ADMIN_SERVICE_ID: "service-a" } },
    dispatchEvent: events.dispatchEvent.bind(events),
    fetch: async (_url: string, init: RequestInit) => {
      requestHeaders = init.headers as Record<string, string>;
      return { ok: status === 200, status, json: async () => status === 200 ? [] : { detail: { error: "denied" } } };
    },
  });
  const cache = new Map<string, any>();
  // Compile only the modules under test; no Next config or actual env files are loaded.
  function load(path: string): any {
    if (cache.has(path)) return cache.get(path);
    const module = { exports: {} };
    cache.set(path, module.exports);
    const source = ts.transpileModule(readFileSync(path, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
    vm.runInContext(`(function(require,module,exports){${source}\n})`, context)(
      (name: string) => name.startsWith(".") ? load(resolve(dirname(path), `${name}.ts`)) : require(name), module, module.exports,
    );
    return module.exports;
  }
  const auth = load(resolve(here, "staff-auth.ts"));
  const api = load(resolve(here, "../lib/admin-api.ts")).adminApi;
  return {
    auth, api, storage, document, window, context, load,
    get options() { return options; }, get rendered() { return rendered; }, get disabled() { return disabled; },
    get headers() { return requestHeaders; },
    respond: (value: number) => { status = value; },
    expire: () => { clock += 61_000; [...timers.values()].forEach((callback) => callback()); },
  };
}

test("missing Google client ID fails closed, including saved credentials", async () => {
  const b = browser(credential());
  b.auth.startStaffAuth("");
  assert.equal(b.auth.getStaffToken(), null);
  assert.equal(b.storage.has(key), false);
  assert.equal(b.auth.acceptStaffCredential(credential()), false);
  await assert.rejects(b.auth.renderStaffSignIn({ isConnected: true }, () => {}), /google_client_id_missing/);
  assert.equal(b.rendered, 0);
});

test("unauthenticated API requests have no Bearer; a hint cookie supplies no credential", async () => {
  const b = browser();
  b.auth.startStaffAuth("public-test-client");
  b.document.cookie = "admin_authenticated=1";
  await b.api.jobs();
  assert.equal(b.auth.getStaffToken(), null);
  assert.equal(b.headers.Authorization, undefined);
});

test("GIS popup callback stores ID credential, notifies, sets hint and supplies Bearer", async () => {
  const b = browser();
  b.auth.startStaffAuth("public-test-client");
  let notified = 0;
  const unsubscribe = b.auth.subscribeStaffAuth(() => { notified++; });
  let accepted = false;
  await b.auth.renderStaffSignIn({ isConnected: true }, (value: boolean) => { accepted = value; });
  assert.equal(b.options.ux_mode, "popup");
  assert.equal(b.options.client_id, "public-test-client");
  assert.equal(b.options.hd, undefined);
  assert.equal(b.options.scope, undefined);
  b.options.callback({ credential: credential() });
  assert.equal(accepted, true);
  assert.equal(notified, 1);
  assert.equal(b.storage.get(key), credential());
  assert.equal(b.auth.getStaffAuthState(), "authenticated");
  assert.match(b.document.cookie, /admin_authenticated=1/);
  assert.ok(!b.document.cookie.includes(credential()));
  await b.api.jobs();
  assert.equal(b.headers.Authorization, `Bearer ${credential()}`);
  assert.equal(b.headers["X-Service-ID"], "service-a");
  unsubscribe();
});

test("same-tab reload restores unexpired token and expires active session without a request", () => {
  const b = browser(credential());
  b.auth.startStaffAuth("public-test-client");
  assert.equal(b.auth.getStaffToken(), credential());
  b.expire();
  assert.equal(b.auth.getStaffToken(), null);
  assert.equal(b.auth.getStaffAuthState(), "unauthenticated");
  assert.equal(b.storage.has(key), false);
  assert.match(b.document.cookie, /Max-Age=0/);
});

test("expired and malformed saved tokens are removed", () => {
  for (const saved of [credential(now / 1000 - 1), "invalid", "header.e30.signature"]) {
    const b = browser(saved);
    b.auth.startStaffAuth("public-test-client");
    assert.equal(b.auth.getStaffToken(), null);
    assert.equal(b.storage.has(key), false);
    assert.match(b.document.cookie, /Max-Age=0/);
  }
});

test("storage write failure does not leave a login hint or active session", () => {
  const b = browser();
  b.auth.startStaffAuth("public-test-client");
  vm.runInContext("sessionStorage.setItem = () => { throw new Error('storage unavailable'); }", b.context);
  assert.equal(b.auth.acceptStaffCredential(credential()), false);
  assert.equal(b.auth.getStaffToken(), null);
  assert.match(b.document.cookie, /Max-Age=0/);
});

test("logout clears memory, storage and cookie and disables Google auto-select", async () => {
  const b = browser(credential());
  b.auth.startStaffAuth("public-test-client");
  b.auth.logoutStaff();
  assert.equal(b.auth.getStaffToken(), null);
  assert.equal(b.storage.has(key), false);
  assert.match(b.document.cookie, /Max-Age=0/);
  assert.equal(b.disabled, 1);
  await b.api.jobs();
  assert.equal(b.headers.Authorization, undefined);
});

test("API 401 clears session and allows a new login", async () => {
  const b = browser(credential());
  b.auth.startStaffAuth("public-test-client");
  b.respond(401);
  await assert.rejects(b.api.jobs(), { status: 401 });
  assert.equal(b.auth.getStaffAuthState(), "unauthenticated");
  assert.equal(b.auth.getStaffToken(), null);
  assert.equal(b.storage.has(key), false);
  assert.match(b.document.cookie, /Max-Age=0/);
  assert.equal(b.auth.acceptStaffCredential(credential()), true);
});

test("API 403 preserves the credential and reports forbidden without granting permission", async () => {
  const b = browser(credential());
  b.auth.startStaffAuth("public-test-client");
  b.respond(403);
  await assert.rejects(b.api.jobs(), { status: 403 });
  assert.equal(b.auth.getStaffAuthState(), "forbidden");
  assert.equal(b.auth.getStaffToken(), credential());
  assert.equal(b.storage.get(key), credential());
});

test("production middleware routes to login until the GIS flow sets the UI hint", () => {
  const b = browser();
  vm.runInContext('process.env.APP_ENV = "production"', b.context);
  const { middleware } = b.load(resolve(here, "../../targets/admin/middleware.ts"));
  const request = (path: string, hint?: string) => ({
    nextUrl: { pathname: path, clone: () => new URL(`https://admin.example.test${path}`) },
    cookies: { get: () => hint ? { value: hint } : undefined },
  });
  assert.equal(middleware(request("/")).headers.get("location"), "https://admin.example.test/auth-required");
  assert.equal(middleware(request("/auth-required")).headers.get("x-middleware-next"), "1");
  b.auth.startStaffAuth("public-test-client");
  b.auth.acceptStaffCredential(credential());
  assert.match(b.document.cookie, /admin_authenticated=1/);
  assert.equal(middleware(request("/", "1")).headers.get("x-middleware-next"), "1");
  b.auth.logoutStaff();
  assert.match(b.document.cookie, /Max-Age=0/);
  assert.equal(middleware(request("/")).status, 307);
});

test("production UI mounts login before protected children; forbidden and logout stay explicit", () => {
  const boundary = readFileSync(resolve(here, "AdminAuthBoundary.tsx"), "utf8");
  assert.match(boundary, /state === "unauthenticated"\) return <StaffLogin/);
  assert.match(boundary, /state === "forbidden"/);
  assert.match(boundary, /この画面を利用する権限がありません/);
  assert.match(boundary, /logoutStaff\(\); window.location.replace\("\/auth-required"\)/);
  const layout = readFileSync(resolve(here, "layout.tsx"), "utf8");
  assert.match(layout, /APP_ENV === "production"/);
  const login = readFileSync(resolve(here, "StaffLogin.tsx"), "utf8");
  assert.match(login, /if \(accepted\) window.location.replace\("\/"\)/);
});

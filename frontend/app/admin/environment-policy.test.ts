import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  allowsDemoReset,
  allowsLiffTokenCheck,
  isStagingEnvironment,
  legacyLiffRouteAction,
} from "../lib/environment-policy.ts";
import {
  blockingReasonMessages,
  formatBlockingReasons,
  getBlockingReasonMessage,
} from "./blocking-reasons.ts";

test("token check is fail-closed outside local development environments", () => {
  assert.deepEqual(
    ["local", "development", "demo", "staging", "production", "unknown", undefined].map(
      (environment) => allowsLiffTokenCheck(environment),
    ),
    [true, true, false, false, false, false, false],
  );
  assert.equal(allowsLiffTokenCheck(" Development "), true);
});

test("demo-capable environments enable reset and staging receives its own presentation", () => {
  assert.deepEqual(
    ["local", "development", "demo", "staging", "production", "unknown", undefined].map(
      (environment) => allowsDemoReset(environment),
    ),
    [true, true, true, false, false, false, false],
  );
  assert.equal(isStagingEnvironment(" staging "), true);
  assert.equal(isStagingEnvironment("demo"), false);
});

test("middleware is limited to token check and APP_ENV stays server-side", async () => {
  const middleware = await readFile(new URL("../../middleware.ts", import.meta.url), "utf8");
  const nextConfig = await readFile(new URL("../../next.config.js", import.meta.url), "utf8");
  assert.match(middleware, /"\/liff-token-check"/);
  assert.match(middleware, /"\/demo\/liff\/:path\*"/);
  assert.match(middleware, /allowsLiffTokenCheck\(process\.env\.APP_ENV\)/);
  assert.match(middleware, /status:\s*404/);
  assert.doesNotMatch(middleware, /console\./);
  assert.match(middleware, /new NextResponse\(null, \{ status: 404 \}\)/);
  assert.match(nextConfig, /"APP_ENV"/);
  assert.doesNotMatch(nextConfig, /NEXT_PUBLIC_APP_ENV/);
});

test("legacy LIFF routes redirect only in staging and fail closed in production", () => {
  assert.deepEqual(
    ["local", "development", "demo", "staging", "production", "unknown", undefined].map(
      (environment) => legacyLiffRouteAction(environment),
    ),
    ["next", "next", "next", "redirect", "not_found", "not_found", "not_found"],
  );
});

test("legacy LIFF redirect preserves path identifiers and query through URL cloning", async () => {
  const middleware = await readFile(new URL("../../middleware.ts", import.meta.url), "utf8");
  assert.match(middleware, /request\.nextUrl\.clone\(\)/);
  assert.match(middleware, /replace\(\s*\/\^\\\/demo\\\/liff\//);
  assert.match(middleware, /NextResponse\.redirect\(destination, 307\)/);
});

test("staging omits the reset control and uses verification copy", async () => {
  const page = await readFile(new URL("./page.tsx", import.meta.url), "utf8");
  const layout = await readFile(new URL("./layout.tsx", import.meta.url), "utf8");
  assert.match(page, /allowDemoReset\s*&&\s*<div/);
  assert.match(page, />デモデータをリセット<\/button>/);
  assert.match(layout, /準本番検証環境/);
  assert.match(layout, /現在のLINE送信モードと送信可否を画面内で確認/);
  assert.match(layout, /送信時にはBackendでも再検証/);
  assert.doesNotMatch(layout, /業務データはモックです|現在は実LINE通知を送信しません|Backend再起動で一時データが初期化されます/);
  assert.match(layout, /LOCAL DEMO/);
  assert.match(layout, /ローカルデモ環境/);
});

test("Admin and LIFF clients use owner-specific API configuration", async () => {
  const adminConfig = await readFile(new URL("../lib/admin-config.ts", import.meta.url), "utf8");
  const lineConfig = await readFile(new URL("../lib/line-config.ts", import.meta.url), "utf8");
  const admin = await readFile(new URL("../lib/admin-api.ts", import.meta.url), "utf8");
  const liff = await readFile(new URL("../lib/liff-api.ts", import.meta.url), "utf8");
  assert.match(adminConfig, /NEXT_PUBLIC_ADMIN_API_BASE_URL/);
  assert.match(lineConfig, /NEXT_PUBLIC_LINE_API_BASE_URL/);
  assert.match(admin, /import \{ ADMIN_API_BASE \}/);
  assert.match(liff, /import \{ LINE_API_BASE \}/);
  for (const source of [admin, liff]) {
    assert.doesNotMatch(source, /https:\/\/[^"'`]+ngrok/);
    assert.doesNotMatch(source, /https?:\/\/(localhost|127\.0\.0\.1)/);
  }
});

test("Admin exposes safe staging LINE mode and enforces one-recipient UI", async () => {
  const page = await readFile(new URL("./page.tsx", import.meta.url), "utf8");
  const panels = await readFile(new URL("./MajorPanels.tsx", import.meta.url), "utf8");
  const policy = await readFile(new URL("./notification-ui-state.ts", import.meta.url), "utf8");
  const admin = await readFile(new URL("../lib/admin-api.ts", import.meta.url), "utf8");
  assert.match(admin, /\/admin\/line-send-mode/);
  assert.match(admin, /notification-link/);
  assert.match(page, /isLiveMode\(lineSendMode\)/);
  assert.match(page, /canAttemptSend\(lineSendMode/);
  assert.match(page, /deriveNotificationUiState/);
  assert.match(page, /canSend=\{workflowState\.canSend\}/);
  assert.match(policy, /args\.selectedCount === 1/);
  assert.match(policy, /args\.validation\.selected_count === 1/);
  assert.match(policy, /args\.validation\.sendable_count === 1/);
  assert.match(policy, /args\.validationCurrent/);
  assert.match(policy, /!args\.liveBlocked/);
  assert.match(policy, /args\.liveLinkReady/);
  assert.match(policy, /!args\.queueFailure/);
  assert.match(panels, /現在の送信モードと送信可能な対象者を確認/);
  assert.match(panels, /formatBlockingReasons\(lineSendMode\)/);
  assert.match(panels, /送信後は取り消せません/);
  assert.match(page, /notificationLink/);
  assert.match(page, /通知送信結果/);
  assert.match(page, /canAttemptSend\(lineSendMode/);
  assert.doesNotMatch(page, /STAGING_LINE_ALLOWED_SUBJECTS/);
  assert.doesNotMatch(page, /STAGING_LINE_ALLOWED_MEMBER_ID/);
  assert.doesNotMatch(page, /LINE_MESSAGING_CHANNEL_ACCESS_TOKEN/);
  assert.doesNotMatch(page, /line_subject/);
});

test("staging live blocked reasons use the complete safe Japanese mapping", () => {
  assert.deepEqual(Object.keys(blockingReasonMessages), [
    "sending_disabled",
    "live_send_disabled",
    "line_capability_unavailable",
    "invalid_max_recipients",
    "allowlist_missing",
    "message_prefix_missing",
    "access_token_missing",
    "staff_authenticator_invalid",
    "liff_url_invalid",
  ]);
  assert.deepEqual(
    formatBlockingReasons({
      mode: "staging_live",
      max_recipients: 1,
      message_prefix: null,
      ready: false,
      blocking_reasons: Object.keys(blockingReasonMessages),
    }),
    Object.values(blockingReasonMessages),
  );
  for (const code of Object.keys(blockingReasonMessages)) {
    assert.doesNotMatch(getBlockingReasonMessage(code), new RegExp(code));
  }
});

test("blocked reason formatting deduplicates reasons and hides unknown codes", () => {
  const unknownCode = "unexpected_internal_reason";
  assert.deepEqual(
    formatBlockingReasons({
      mode: "staging_live",
      max_recipients: 1,
      message_prefix: null,
      ready: false,
      blocking_reasons: ["allowlist_missing", "allowlist_missing", unknownCode],
    }),
    [
      blockingReasonMessages.allowlist_missing,
      "実LINE送信の準備が完了していません。",
    ],
  );
  assert.doesNotMatch(getBlockingReasonMessage(unknownCode), new RegExp(unknownCode));
});

test("blocked reasons are hidden for empty, fake, and live ready modes", () => {
  assert.deepEqual(formatBlockingReasons({ mode: "staging_live", max_recipients: 1, message_prefix: null, ready: false, blocking_reasons: [] }), []);
  assert.deepEqual(formatBlockingReasons({ mode: "fake", max_recipients: null, message_prefix: null, ready: false, blocking_reasons: ["allowlist_missing"] }), [blockingReasonMessages.allowlist_missing]);
  assert.deepEqual(formatBlockingReasons({ mode: "staging_live", max_recipients: 1, message_prefix: "configured", ready: true, blocking_reasons: ["allowlist_missing"] }), []);
});

test("Admin renders only safe blocked messages and keeps sending disabled", async () => {
  const page = await readFile(new URL("./page.tsx", import.meta.url), "utf8");
  const panels = await readFile(new URL("./MajorPanels.tsx", import.meta.url), "utf8");
  assert.match(panels, /formatBlockingReasons\(lineSendMode\)/);
  assert.match(panels, /reasons\.length/);
  assert.match(panels, /送信モードが利用できません/);
  assert.match(page, /canSend=\{workflowState\.canSend\}/);
  assert.match(panels, /disabled=\{!canSend \|\| !send\}/);
  assert.doesNotMatch(panels, /invalid_max_recipients|allowlist_missing|message_prefix_missing|access_token_missing|staff_authenticator_invalid|liff_url_invalid/);
});

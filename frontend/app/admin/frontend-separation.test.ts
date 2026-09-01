import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("LINE and Admin target roots contain only their owned private routes", () => {
  const lineRoot = read("../../targets/line/app/page.tsx");
  const lineLayout = read("../../targets/line/app/layout.tsx");
  const adminRoot = read("../../targets/admin/app/page.tsx");
  const adminMiddleware = read("../../targets/admin/middleware.ts");
  assert.doesNotMatch(`${lineRoot}${lineLayout}`, /app\/admin|admin-api/);
  assert.doesNotMatch(`${adminRoot}${adminMiddleware}`, /app\/liff|liff-api|LIFF/);
  assert.match(adminRoot, /AdminPage/);
  assert.match(lineRoot, /redirect\("\/liff"\)/);
});

test("frontend target configs expose no backend credentials", () => {
  const files = [
    read("../../targets/line/next.config.js"),
    read("../../targets/admin/next.config.js"),
    read("../../targets/line/middleware.ts"),
    read("../../targets/admin/middleware.ts"),
  ].join("\n");
  assert.doesNotMatch(files, /bearer_token|access_token|webhook_secret|channel_secret/i);
});

test("Admin guard is supplemental and API authentication failures remain explicit", () => {
  const middleware = read("../../targets/admin/middleware.ts");
  const client = read("../lib/admin-api.ts");
  assert.match(middleware, /APP_ENV === "production"/);
  assert.match(middleware, /admin_authenticated/);
  assert.match(middleware, /\/auth-required/);
  assert.match(client, /Authorization: `Bearer \$\{accessToken\}`/);
  assert.match(client, /response\.status === 401 \|\| response\.status === 403/);
  assert.doesNotMatch(`${middleware}${client}`, /client_secret|OIDC_CLIENT_SECRET/i);
});

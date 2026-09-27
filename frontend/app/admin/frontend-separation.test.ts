import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("Admin target builds and serves only its owned routes", () => {
  const root = read("../../targets/admin/app/page.tsx");
  const middleware = read("../../targets/admin/middleware.ts");
  const pkg = JSON.parse(read("../../package.json"));
  assert.match(root, /AdminLayout/);
  assert.match(root, /AdminPage/);
  assert.doesNotMatch(root + middleware, /app\/liff|liff-api|LIFF/);
  assert.equal(pkg.scripts.dev, "next dev targets/admin");
  assert.equal(pkg.scripts.build, "next build targets/admin");
  assert.equal(pkg.scripts.start, "next start targets/admin");
});

test("frontend target configs expose no backend credentials", () => {
  const files = [
    read("../../targets/admin/next.config.js"),
    read("../../targets/admin/middleware.ts"),
  ].join("\n");
  const config = read("../../targets/admin/next.config.js");
  assert.match(config, /loadTargetEnv\("admin"\)/);
  assert.match(config, /distDir: ".next-admin"/);
  assert.doesNotMatch(config, /NEXT_PUBLIC_APP_ENV|env\s*:/);
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

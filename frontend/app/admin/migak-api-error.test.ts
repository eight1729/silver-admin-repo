import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import ts from "typescript";

test("external validation limit explains correction separately from send capability", () => {
  const source = readFileSync(new URL("../lib/admin-api.ts", import.meta.url), "utf8");
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const module = { exports: {} as any };
  runInNewContext(code, { module, exports: module.exports,
    require: () => ({ ADMIN_API_BASE: "https://admin.invalid" }) });
  const { AdminApiError, adminErrorMessage } = module.exports;
  const message = adminErrorMessage(new AdminApiError(422, "external_target_limit_exceeded"));
  assert.match(message, /外部業務API/);
  assert.match(message, /500人以下に減らして再検証/);
  assert.match(message, /送信可能人数は別の制限/);
});

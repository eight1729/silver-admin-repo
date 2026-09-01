import assert from "node:assert/strict";
import test from "node:test";
import { access, readFile } from "node:fs/promises";

const routeFiles = {
  dashboard: new URL("./dashboard/page.tsx", import.meta.url),
  jobs: new URL("./jobs/page.tsx", import.meta.url),
  history: new URL("./history/page.tsx", import.meta.url),
  reports: new URL("./reports/page.tsx", import.meta.url),
  settings: new URL("./settings/page.tsx", import.meta.url),
  members: new URL("./members/page.tsx", import.meta.url),
};

test("every sidebar target has a real page and pathname-based current state", async () => {
  await Promise.all(Object.values(routeFiles).map((file) => access(file)));
  const shell = await readFile(new URL("./AdminShell.tsx", import.meta.url), "utf8");
  const expected = ["/admin/dashboard", "/admin/jobs", "/admin", "/admin/history", "/admin/reports", "/admin/settings"];
  for (const href of expected) assert.match(shell, new RegExp(`href: "${href.replaceAll("/", "\\/")}"`));
  assert.match(shell, /pathname === item\.href/);
  assert.match(shell, /aria-current=\{current \? "page" : undefined\}/);
  assert.equal((shell.match(/href:/g) ?? []).length, 6);
});

test("candidate member route is read-only and reuses the existing job-scoped candidates API", async () => {
  const members = await readFile(routeFiles.members, "utf8");
  assert.match(members, /adminApi\.candidates\(selectedJobId/);
  assert.match(members, /対象候補会員一覧/);
  assert.doesNotMatch(members, /method:\s*["'](?:PUT|POST|DELETE)|updateTargets|send|validate/);
});

test("jobs route is read-only and uses only the existing jobs API", async () => {
  const jobs = await readFile(routeFiles.jobs, "utf8");
  assert.match(jobs, /adminApi\.jobs/);
  assert.match(jobs, /求人ID/);
  assert.match(jobs, /href="\/admin"/);
  assert.doesNotMatch(jobs, /method:\s*["'](?:PUT|POST|DELETE)|update|delete|createJob/);
});

test("history route is explicitly limited to the stored current operation", async () => {
  const history = await readFile(routeFiles.history, "utf8");
  assert.match(history, /ADMIN_OPERATION_STORAGE_KEY/);
  assert.match(history, /adminApi\.operation\(operationId/);
  assert.match(history, /adminApi\.deliveries\(operationId/);
  assert.match(history, /全operationの一覧取得手段はありません/);
  assert.match(history, /正式な監査履歴ではありません/);
  assert.doesNotMatch(history, /member_id|provider_request_id|line_subject/);
});

test("reports expose no invented metrics and settings expose no sensitive values", async () => {
  const reports = await readFile(routeFiles.reports, "utf8");
  const settings = await readFile(routeFiles.settings, "utf8");
  assert.match(reports, /取得手段がないため、指標は表示していません/);
  assert.doesNotMatch(reports, /\d+%|開封率|応募率|反応率/);
  assert.match(settings, /機密設定値は表示していません/);
  assert.doesNotMatch(settings, /access.token|channel.secret|LIFF.ID|allowlist|service_id/i);
});

test("dashboard stays an honest notification entry without aggregate figures", async () => {
  const dashboard = await readFile(routeFiles.dashboard, "utf8");
  assert.match(dashboard, /href="\/admin"/);
  assert.match(dashboard, /累計件数や全operationの集計は、取得手段がないため表示していません/);
  assert.doesNotMatch(dashboard, /開封|興味あり|辞退|応募/);
});

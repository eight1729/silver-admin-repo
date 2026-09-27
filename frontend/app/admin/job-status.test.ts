import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import type { AdminJobDetail, AdminJobSummary, JobStatus } from "../lib/admin-api";
import { jobStatusLabel } from "./job-status.ts";

const cases = [
  ["draft", "下書き"], ["published", "募集中"], ["paused", "停止中"],
  ["closed", "募集終了"], ["cancelled", "取消"], ["unknown", "状態不明"],
] as const satisfies readonly (readonly [JobStatus, string])[];
const source = (path: string) => readFile(new URL(path, import.meta.url), "utf8");

for (const [status, label] of cases) {
  test(`canonical JobStatus ${status} is accepted by both response types and has a label`, () => {
    const summaryStatus: AdminJobSummary["status"] = status;
    const detailStatus: AdminJobDetail["status"] = status;
    assert.equal(jobStatusLabel(summaryStatus), label);
    assert.equal(jobStatusLabel(detailStatus), label);
  });
}

test("frontend union matches Backend enum and Admin Public artifact exactly", async () => {
  const enumSource = await source("../../../backend/app/domain/enums/enums.py");
  const enumBlock = enumSource.split("class JobStatus(str, Enum):")[1].split("class ")[0];
  const backendValues = [...enumBlock.matchAll(/= "([a-z_]+)"/g)].map((match) => match[1]);
  const apiSource = await source("../lib/admin-api.ts");
  const union = apiSource.match(/export type JobStatus = ([^;]+);/)![1];
  const frontendValues = [...union.matchAll(/"([a-z_]+)"/g)].map((match) => match[1]);
  const artifact = JSON.parse(await source("../../../backend/contracts/admin-api-v1.openapi.json"));
  assert.deepEqual(frontendValues, backendValues);
  assert.deepEqual(artifact.components.schemas.JobStatus.enum, backendValues);
  assert.deepEqual(cases.map(([status]) => status), backendValues);
  const schema = await source("../../../backend/app/schemas/admin.py");
  for (const model of ["AdminJobSummaryResponse", "AdminJobDetailResponse"]) {
    assert.match(schema.split(`class ${model}(BaseModel):`)[1].split("class ")[0], /status: JobStatus/);
    assert.equal(artifact.components.schemas[model].properties.status.$ref, "#/components/schemas/JobStatus");
  }
});

test("suspended is rejected by the type and absent from runtime definitions and displays", async () => {
  // @ts-expect-error Legacy status is not part of the current Admin contract.
  const legacy: JobStatus = "suspended";
  assert.equal(legacy, "suspended");
  for (const path of ["../lib/admin-api.ts", "./job-status.ts", "./MajorPanels.tsx", "./jobs/page.tsx", "./page.tsx"]) {
    assert.doesNotMatch(await source(path), /suspended/);
  }
});

test("every job display uses the exhaustive label mapping and preserves existing closed wording", async () => {
  const major = await source("./MajorPanels.tsx");
  const jobs = await source("./jobs/page.tsx");
  const page = await source("./page.tsx");
  // MajorPanels no longer renders a status label; remove its unused legacy mapping.
  assert.doesNotMatch(major, /function jobStatusLabel/);
  assert.match(jobs, /import \{ jobStatusLabel \} from "\.\.\/job-status"/);
  assert.match(jobs, /jobStatusLabel\(job.status\)/);
  assert.match(page, /value === "closed" \? "終了" : jobStatusLabel\(value\)/);
});

test("existing published-only selection and notification guards remain in place", async () => {
  const major = await source("./MajorPanels.tsx");
  const page = await source("./page.tsx");
  assert.match(major, /const selectable = item.status === "published";/);
  assert.match(major, /const disabled = busy \|\| !selectable;/);
  assert.match(major, /disabled=\{busy \|\| selected.size === 0 \|\| \(singleRecipient && selected.size !== 1\) \|\| job.status !== "published"\}/);
  assert.match(page, /job.status !== "published" && <div className="admin-error">この求人は募集中ではありません。/);
  assert.match(page, /disabled=\{!job \|\| !selected.size \|\| busy \|\| job.status !== "published"\}/);
});

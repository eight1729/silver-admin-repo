import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { filterRegisteredJobs, formatJobRegistration, registrationLowerBound } from "./job-registration.ts";
import type { AdminJobSummary } from "../lib/admin-api.ts";

const job = (job_id: string, created_at?: string | null): AdminJobSummary => ({
  job_id, created_at, title: "求人", status: "published", location: null,
  openings: 1, summary: null, version: "2099-12-31T00:00:00Z",
});

test("JST midnight is inclusive and filtering preserves server ordering", () => {
  const jobs = [job("after", "2026-10-13T15:00:00.001Z"), job("exact", "2026-10-14T00:00:00+09:00"),
    job("before", "2026-10-13T14:59:59.999Z"), job("missing"), job("null", null)];
  assert.deepEqual(filterRegisteredJobs(jobs, "2026-10-14").map(j => j.job_id), ["after", "exact"]);
  assert.equal(filterRegisteredJobs(jobs, ""), jobs);
  assert.equal(jobs.length, 5);
});

test("all records, including beyond 20, are filtered before any display slicing", () => {
  const jobs = Array.from({ length: 213 }, (_, n) => job(String(n), "2026-10-14T00:00:00+09:00"));
  assert.equal(filterRegisteredJobs(jobs, "2026-10-14").length, 213);
});

test("invalid dates do not turn into an unfiltered list", () => {
  for (const date of ["2026-02-29", "2026-04-31", "2026-13-01", "2026-1-01", "garbage", "0000-01-01"]) {
    assert.equal(registrationLowerBound(date), null);
    assert.deepEqual(filterRegisteredJobs([job("a", "2026-12-01T00:00:00Z")], date), []);
  }
  assert.equal(registrationLowerBound("2024-02-29"), Date.parse("2024-02-28T15:00:00Z"));
});

test("registration display always uses Japan time; missing is never version", () => {
  assert.equal(formatJobRegistration("2026-10-13T15:00:00Z"), "2026/10/14");
  assert.equal(formatJobRegistration("2026-10-13T14:59:59Z"), "2026/10/13");
  for (const value of [undefined, null, "invalid"]) assert.equal(formatJobRegistration(value), "未取得");
});

test("both surfaces use the same filter/display and keep notification selection untouched", () => {
  const listing = readFileSync(new URL("./jobs/page.tsx", import.meta.url), "utf8");
  const panels = readFileSync(new URL("./MajorPanels.tsx", import.meta.url), "utf8");
  const selection = panels.split("export function JobSelectionPanel")[1].split("export function CandidateSelectionPanel")[0];
  for (const source of [listing, selection]) {
    assert.match(source, /filterRegisteredJobs\(jobs, registeredFrom\)/);
    assert.match(source, /<JobDateFilter value=\{registeredFrom\} onChange=\{setRegisteredFrom\}/);
    assert.match(source, /formatJobRegistration\(/);
    assert.match(source, /visibleJobs.map/);
  }
  assert.doesNotMatch(listing, /job.version/);
  assert.match(listing, /<LoadingOverlay active=\{loading\}/);
  assert.doesNotMatch(selection, /setSelectedJob|setOperation|setCandidates/);
  assert.match(selection, /item.status === "published"/);
  assert.match(selection, /選択は保持しています/);
});

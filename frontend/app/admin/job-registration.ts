import type { AdminJobSummary } from "../lib/admin-api";

// Date inputs use the business timezone, independently of the browser timezone.
export function registrationLowerBound(value: string): number | null {
  if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value) || value.startsWith("0000")) return null;
  const utc = new Date(`${value}T00:00:00Z`);
  if (!Number.isFinite(utc.getTime()) || utc.toISOString().slice(0, 10) !== value) return null;
  return Date.parse(`${value}T00:00:00+09:00`);
}

export function filterRegisteredJobs(jobs: AdminJobSummary[], from: string): AdminJobSummary[] {
  if (!from) return jobs;
  const bound = registrationLowerBound(from);
  if (bound === null) return [];
  // The backend has already fetched and ordered the complete result. Never use
  // updated_at or version when a provider has not supplied registration dates.
  return jobs.filter((job) => job.created_at != null && Date.parse(job.created_at) >= bound);
}

export function formatJobRegistration(value?: string | null): string {
  if (!value || !Number.isFinite(Date.parse(value))) return "未取得";
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date(value));
}

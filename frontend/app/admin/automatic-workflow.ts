import { orderCandidates } from "./candidate-order.ts";
import type { AdminCandidate } from "../lib/admin-api";

export type SelectionMode = "auto" | "manual";
export const AUTO_OPERATION_KEY = "silver-admin-auto-operation";

export function parseNotificationEntry(search: string): { mode: SelectionMode | null; jobId: string | null } {
  const query = new URLSearchParams(search);
  const mode = query.get("mode");
  const id = query.get("jobId");
  if (query.getAll("mode").length > 1 || query.getAll("jobId").length > 1 ||
      (mode !== null && mode !== "auto" && mode !== "manual") ||
      (id !== null && !/^[A-Za-z0-9_-]{1,128}$/.test(id))) return { mode: null, jobId: null };
  return { mode, jobId: id };
}

export function notificationEntryUrl(mode: SelectionMode, jobId?: string | null): string {
  const query = new URLSearchParams({ mode });
  if (jobId) query.set("jobId", jobId);
  return `/admin?${query}`;
}

export function orderAutomaticCandidates(candidates: readonly AdminCandidate[], selected: Set<string>): AdminCandidate[] {
  return orderCandidates(candidates, selected);
}

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

export function notificationEntryUrl(mode: SelectionMode, jobId?: string | null, operationId?: string | null): string {
  const query = new URLSearchParams({ mode });
  if (jobId) query.set("jobId", jobId);
  if (operationId) query.set("operationId", operationId);
  return `/admin?${query}`;
}

export function parseResumeOperation(search: string): string | null {
  const query = new URLSearchParams(search);
  const id = query.get("operationId");
  if (query.getAll("operationId").length !== 1 || !id ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) return null;
  return id;
}

export function orderAutomaticCandidates(candidates: readonly AdminCandidate[], selected: Set<string>): AdminCandidate[] {
  return orderCandidates(candidates, selected);
}

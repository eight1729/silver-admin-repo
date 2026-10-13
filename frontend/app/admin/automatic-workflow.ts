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
  const numeric = (value?: string | null) => value && /^[0-9]+$/.test(value) ? value.replace(/^0+/, "") || "0" : null;
  return [...candidates].sort((a, b) => {
    const selection = Number(selected.has(b.member_id)) - Number(selected.has(a.member_id));
    if (selection) return selection;
    const level = (b.recommendation_level ?? 0) - (a.recommendation_level ?? 0);
    if (level) return level;
    const x = numeric(a.member_number), y = numeric(b.member_number);
    if (x !== y) {
      if (x === null) return 1;
      if (y === null) return -1;
      if (x.length !== y.length) return y.length - x.length;
      return x > y ? -1 : 1;
    }
    return a.member_id < b.member_id ? -1 : a.member_id > b.member_id ? 1 : 0;
  });
}

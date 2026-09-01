import type { AdminCandidate } from "../lib/admin-api";

export type CandidateFilterId = "all" | "line_linked" | "eligible";

export const candidateFilters: ReadonlyArray<{ id: CandidateFilterId; label: string }> = [
  { id: "all", label: "すべて" },
  { id: "line_linked", label: "LINE連携済み" },
  { id: "eligible", label: "送信可能" },
];

export function filterCandidates(candidates: readonly AdminCandidate[], filter: CandidateFilterId): AdminCandidate[] {
  if (filter === "line_linked") return candidates.filter((candidate) => candidate.line_linked);
  if (filter === "eligible") return candidates.filter((candidate) => candidate.eligible);
  return [...candidates];
}

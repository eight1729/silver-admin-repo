import type { AdminCandidate } from "../lib/admin-api";

export type CandidateFilterId = "all" | "line_linked" | "eligible";

export const candidateFilters: ReadonlyArray<{ id: CandidateFilterId; label: string }> = [
  { id: "all", label: "すべて" },
  { id: "line_linked", label: "LINE連携済み" },
  { id: "eligible", label: "送信可能" },
];

export function isMemberNumber(value: string): boolean {
  return value.length > 0 && !/[^0-9]/.test(value);
}

/** Compare unsigned decimal strings without losing precision or changing display values. */
export function memberNumberAtLeast(value: string | null | undefined, minimum: string): boolean {
  if (minimum === "") return true;
  if (value == null || !isMemberNumber(value) || !isMemberNumber(minimum)) return false;
  const left = value.replace(/^0+/, "") || "0";
  const right = minimum.replace(/^0+/, "") || "0";
  return left.length !== right.length ? left.length > right.length : left >= right;
}

export function filterCandidates(candidates: readonly AdminCandidate[], filter: CandidateFilterId, minimumMemberNumber = ""): AdminCandidate[] {
  return candidates.filter((candidate) =>
    (filter !== "line_linked" || candidate.line_linked)
    && (filter !== "eligible" || candidate.eligible)
    && memberNumberAtLeast(candidate.member_number, minimumMemberNumber));
}

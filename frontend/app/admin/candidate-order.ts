/** Display order only; preserve opaque identifiers and the input array. */
export function orderCandidates<T extends { member_number?: string | null }>(candidates: readonly T[]): T[] {
  return [...candidates].sort((a, b) => {
    if (a.member_number == null) return b.member_number == null ? 0 : 1;
    if (b.member_number == null) return -1;
    return a.member_number < b.member_number ? -1 : a.member_number > b.member_number ? 1 : 0;
  });
}

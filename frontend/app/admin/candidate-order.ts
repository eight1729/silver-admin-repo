/** Display order only. Never rewrite display values or selection identifiers. */
export function orderCandidates<T extends { member_id: string; member_number?: string | null; recommendation_level?: number | null }>(candidates: readonly T[], selected: Set<string> = new Set()): T[] {
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

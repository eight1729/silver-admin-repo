/** Preserve the selection across pages/filters; a finite capability limit never replaces it. */
export function toggleCandidateSelection(selected: ReadonlySet<string>, memberId: string, maxRecipients: number | null): Set<string> {
  const next = new Set(selected);
  if (next.has(memberId)) next.delete(memberId);
  else if (maxRecipients === null || next.size < maxRecipients) next.add(memberId);
  return next;
}

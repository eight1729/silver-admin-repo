/** Unselected candidates are informational, not validation problems. */
export function validationProblemReasons(reasons: readonly string[]): string[] {
  return reasons.filter((reason) => reason !== "not_selected");
}

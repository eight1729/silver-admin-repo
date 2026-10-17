export function pageWindow(requestedPage: number, totalPages: number) {
  const total = Math.max(1, Math.trunc(totalPages) || 1);
  const current = Math.max(1, Math.min(total, Math.trunc(requestedPage) || 1));
  const start = Math.max(1, current - 3), end = Math.min(total, current + 3);
  return { current, pages: Array.from({ length: end - start + 1 }, (_, i) => start + i),
    before: start > 1, after: end < total };
}

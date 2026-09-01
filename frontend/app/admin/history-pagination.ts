export function paginateHistory<T>(items: readonly T[], requestedPage: number, pageSize = 5) {
  const safePageSize = Math.max(1, Math.trunc(pageSize));
  const totalPages = Math.max(1, Math.ceil(items.length / safePageSize));
  const currentPage = Math.min(Math.max(1, Math.trunc(requestedPage)), totalPages);
  const startIndex = (currentPage - 1) * safePageSize;
  const pageItems = items.slice(startIndex, startIndex + safePageSize);
  return {
    currentPage,
    totalPages,
    pageItems,
    rangeStart: pageItems.length ? startIndex + 1 : 0,
    rangeEnd: startIndex + pageItems.length,
    totalItems: items.length,
    showPagination: items.length > safePageSize,
  };
}

export function containsNewHistory(previousIds: readonly string[], currentIds: readonly string[]): boolean {
  if (previousIds.length === 0) return false;
  const previous = new Set(previousIds);
  return currentIds.some((id) => !previous.has(id));
}

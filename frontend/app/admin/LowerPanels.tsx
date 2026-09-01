import { useEffect, useRef, useState } from "react";
import type { AdminDeliveries, AdminOperation } from "../lib/admin-api";
import { createDeliveryGradient, summarizeDeliveries } from "./delivery-summary";
import { containsNewHistory, paginateHistory } from "./history-pagination";
import { buildOperationHistory, type SessionHistoryEvent } from "./operation-history";

export function DeliverySummaryPanel({ operation, deliveries, loading, error, retry }: { operation: AdminOperation | null; deliveries: AdminDeliveries | null; loading: boolean; error: string; retry: () => Promise<void> }) {
  if (!operation) return <p className="admin-panel-empty">通知を作成すると、このoperationの配信状況が表示されます。</p>;
  if (loading) return <div className="admin-info" role="status">配信結果を読み込んでいます。</div>;
  if (error) return <div className="admin-error" role="alert"><p>{error}</p><button className="admin-button secondary" type="button" onClick={() => void retry()}>配信結果を再読み込み</button></div>;
  if (!deliveries || deliveries.items.length === 0) return <p className="admin-panel-empty">まだ送信結果はありません。</p>;
  const summary = summarizeDeliveries(deliveries);
  const gradient = createDeliveryGradient(summary.items, summary.total);
  const legendColumns = [summary.items.slice(0, 3), summary.items.slice(3)];
  return <div className="delivery-summary-panel">
    <div className="delivery-summary-cards">{summary.items.map((item) => <div className={`delivery-summary-card delivery-summary-card--${item.status}`} key={item.status}><span>{item.label}</span><strong>{item.count}件</strong></div>)}</div>
    <div className="delivery-summary-body">
      <div className="delivery-donut" role="img" aria-label={`現在のoperationの配信結果、合計${summary.total}件`} style={{ background: gradient }}><span><strong>{summary.total}</strong><small>合計</small></span></div>
      <div className="delivery-legend">{legendColumns.map((column, columnIndex) => <dl className="delivery-legend-column" key={columnIndex}>{column.map((item) => <div className="delivery-legend-item" key={item.status}><dt><span className="delivery-legend-bar" style={{ backgroundColor: item.color }} aria-hidden="true" />{item.label}</dt><dd>{item.count}件 <span>（{((item.count / summary.total) * 100).toFixed(1)}%）</span></dd></div>)}</dl>)}</div>
    </div>
    {summary.items.find((item) => item.status === "unknown")?.count ? <p className="admin-info">結果不明の通知は送信結果を確定できません。自動再送は行われません。</p> : null}
  </div>;
}

export function RecentOperationHistory({ operation, jobName, deliveries, sessionEvents }: { operation: AdminOperation | null; jobName: string | null; deliveries: AdminDeliveries | null; sessionEvents: readonly SessionHistoryEvent[] }) {
  const history = buildOperationHistory(operation, jobName, deliveries, sessionEvents, Number.MAX_SAFE_INTEGER);
  const [page, setPage] = useState(1);
  const previousOperationId = useRef<string | null>(null);
  const previousHistoryIds = useRef<string[]>([]);
  const operationId = operation?.operation_id ?? null;
  const historyIds = history.map((item) => item.id);
  const operationChanged = previousOperationId.current !== null && previousOperationId.current !== operationId;
  const historyAdded = previousOperationId.current === operationId && containsNewHistory(previousHistoryIds.current, historyIds);
  const requestedPage = operationChanged || historyAdded ? 1 : page;
  const pagination = paginateHistory(history, requestedPage);
  useEffect(() => {
    if (operationChanged || historyAdded) setPage(1);
    else if (page !== pagination.currentPage) setPage(pagination.currentPage);
    previousOperationId.current = operationId;
    previousHistoryIds.current = historyIds;
  }, [historyAdded, historyIds.join("|"), operationChanged, operationId, page, pagination.currentPage]);
  if (!operation) return <p className="admin-panel-empty">通知operationを作成すると、この画面で確認できる操作を表示します。</p>;
  if (history.length === 0) return <p className="admin-panel-empty">表示できる操作履歴はありません。</p>;
  return <div className="recent-history"><ol>{pagination.pageItems.map((item) => <li className="recent-history-row" key={item.id}><time dateTime={item.occurredAt}>{formatTime(item.occurredAt)}</time><span className="recent-history-icon" aria-hidden="true">{historyIcon(item.name)}</span><strong>{item.name}</strong><span className="recent-history-description">{item.description}</span><span className="recent-history-actor">—</span></li>)}</ol>{pagination.showPagination && <nav className="history-pagination" aria-label="最近の操作履歴のページ切り替え"><span>{pagination.rangeStart}〜{pagination.rangeEnd}件 / 全{pagination.totalItems}件</span><div><button className="admin-button secondary compact" type="button" disabled={pagination.currentPage === 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>前へ</button>{Array.from({ length: pagination.totalPages }, (_, index) => index + 1).map((pageNumber) => <button className={`candidate-page-button${pageNumber === pagination.currentPage ? " is-current" : ""}`} type="button" aria-label={`${pageNumber}ページ目`} aria-current={pageNumber === pagination.currentPage ? "page" : undefined} onClick={() => setPage(pageNumber)} key={pageNumber}>{pageNumber}</button>)}<button className="admin-button secondary compact" type="button" disabled={pagination.currentPage === pagination.totalPages} onClick={() => setPage((value) => Math.min(pagination.totalPages, value + 1))}>次へ</button></div></nav>}</div>;
}

function formatTime(value: string) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "—" : parsed.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function historyIcon(name: string) {
  if (/送信|配信/.test(name)) return "➤";
  if (/検証/.test(name)) return "✓";
  if (/通知/.test(name)) return "✎";
  if (/対象|抽出/.test(name)) return "⌁";
  if (/求人/.test(name)) return "▣";
  return "•";
}

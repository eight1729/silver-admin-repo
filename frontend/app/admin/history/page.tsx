"use client";

import { useEffect, useState } from "react";
import { adminApi, AdminApiError, type AdminDeliveries, type AdminOperation } from "../../lib/admin-api";
import { AdminRouteFrame } from "../AdminRouteFrame";
import { ADMIN_OPERATION_STORAGE_KEY, ADMIN_SELECTED_MEMBERS_STORAGE_KEY } from "../admin-session";
import { RecentOperationHistory } from "../LowerPanels";

export default function AdminHistoryPage() {
  const [operation, setOperation] = useState<AdminOperation | null>(null);
  const [deliveries, setDeliveries] = useState<AdminDeliveries | null>(null);
  const [jobName, setJobName] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    const operationId = sessionStorage.getItem(ADMIN_OPERATION_STORAGE_KEY);
    if (!operationId) { setLoading(false); return; }
    const controller = new AbortController();
    void Promise.all([adminApi.operation(operationId, controller.signal), adminApi.deliveries(operationId, controller.signal)])
      .then(async ([currentOperation, currentDeliveries]) => {
        setOperation(currentOperation); setDeliveries(currentDeliveries);
        const currentJob = await adminApi.job(currentOperation.job_id, controller.signal).catch(() => null);
        setJobName(currentJob?.title ?? null);
      })
      .catch((error) => {
        if (error instanceof AdminApiError && error.status === 404) { sessionStorage.removeItem(ADMIN_OPERATION_STORAGE_KEY); setMissing(true); }
        else if (!(error instanceof DOMException && error.name === "AbortError")) setMissing(true);
      }).finally(() => setLoading(false));
    return () => controller.abort();
  }, []);
  return <AdminRouteFrame title="送信履歴" description="現在の画面セッションで参照できるnotification operationだけを表示します。">
    <div className="admin-info"><p>全operationの一覧取得手段はありません。完全な送信履歴や正式な監査履歴ではありません。</p></div>
    {loading ? <div className="admin-info" role="status">現在のoperationを確認しています。</div> : missing ? <p className="admin-panel-empty">現在参照できるoperationを取得できませんでした。</p> : <RecentOperationHistory operation={operation} jobName={jobName} deliveries={deliveries} sessionEvents={[]} />}
    <div className="admin-history-new-notification"><p>過去の送信履歴は削除されません。</p><a className="admin-button admin-inline-link" href="/admin" onClick={() => { sessionStorage.removeItem(ADMIN_OPERATION_STORAGE_KEY); sessionStorage.removeItem(ADMIN_SELECTED_MEMBERS_STORAGE_KEY); }}>新しい通知を作成</a></div>
  </AdminRouteFrame>;
}

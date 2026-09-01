"use client";

import { useEffect, useState } from "react";
import { adminApi, adminErrorMessage, type AdminCandidate } from "../../lib/admin-api";
import { AdminRouteFrame } from "../AdminRouteFrame";

export default function AdminMembersPage() {
  const [candidates, setCandidates] = useState<AdminCandidate[]>([]);
  const [jobId, setJobId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const selectedJobId = new URLSearchParams(window.location.search).get("jobId")?.trim() ?? "";
    setJobId(selectedJobId);
    if (!selectedJobId) { setLoading(false); return; }
    const controller = new AbortController();
    void adminApi.candidates(selectedJobId, controller.signal).then(setCandidates).catch((value) => {
      if (!(value instanceof DOMException && value.name === "AbortError")) setError(adminErrorMessage(value));
    }).finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  return <AdminRouteFrame title="対象候補会員一覧" description="選択した求人について現在取得できる候補会員を参照専用で表示します。">
    {!jobId && <p className="admin-panel-empty">通知作成画面で求人を選択してから参照してください。</p>}
    {loading && <div className="admin-info" role="status">候補会員を読み込んでいます。</div>}
    {error && <div className="admin-error" role="alert">{error}</div>}
    {!loading && !error && jobId && candidates.length === 0 && <p className="admin-panel-empty">表示できる候補会員はいません。</p>}
    {!loading && !error && candidates.length > 0 && <div className="candidate-table-wrapper"><table className="candidate-selection-table"><thead><tr><th scope="col">会員ID</th><th scope="col">氏名</th><th scope="col">希望条件</th><th scope="col">LINE連携</th><th scope="col">通知可否</th></tr></thead><tbody>{candidates.map((candidate) => <tr key={candidate.member_id}><th scope="row">{candidate.member_id}</th><td>{candidate.display_name || "—"}</td><td>{candidate.preference_summary || "—"}</td><td>{candidate.line_linked ? "連携済み" : "未連携"}</td><td>{candidate.eligible ? "通知可能" : "通知不可"}</td></tr>)}</tbody></table></div>}
    <p><a className="admin-link" href="/admin">通知作成へ戻る</a></p>
  </AdminRouteFrame>;
}

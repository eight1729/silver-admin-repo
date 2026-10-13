"use client";

import { useEffect, useRef, useState } from "react";
import { adminApi, adminErrorMessage, type AdminJobSummary } from "../../lib/admin-api";
import { AdminRouteFrame } from "../AdminRouteFrame";
import { jobStatusLabel } from "../job-status";
import { LoadingOverlay } from "../LoadingOverlay";

export default function AdminJobsPage() {
  const [jobs, setJobs] = useState<AdminJobSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  function load() {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true); setError("");
    void adminApi.jobs(controller.signal).then((items) => {
      if (!controller.signal.aborted) setJobs(items);
    }).catch((value) => {
      if (!controller.signal.aborted && !(value instanceof DOMException && value.name === "AbortError")) setError(adminErrorMessage(value));
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
  }
  useEffect(() => { load(); return () => request.current?.abort(); }, []);
  return <AdminRouteFrame title="求人一覧" description="業務システムから取得した求人を参照専用で表示します。">
    <LoadingOverlay active={loading} />
    {loading && <div className="admin-info" role="status">求人を読み込んでいます。</div>}
    {error && <div className="admin-error" role="alert"><p>{error}</p><button className="admin-button secondary" type="button" onClick={load}>再読み込み</button></div>}
    {!loading && !error && jobs.length === 0 && <p className="admin-panel-empty">現在表示できる求人はありません。</p>}
    {!loading && !error && jobs.length > 0 && <div className="admin-route-card-list">{jobs.map((job) => <article className="admin-card" key={job.job_id}><div className="selection-item-heading"><h3>{job.title}</h3><span className="state-label">{jobStatusLabel(job.status)}</span></div><dl className="compact-details"><div><dt>求人ID</dt><dd>{job.job_id}</dd></div><div><dt>勤務地</dt><dd>{job.location ?? "未設定"}</dd></div><div><dt>募集人数</dt><dd>{job.openings}名</dd></div><div><dt>version</dt><dd>{job.version}</dd></div></dl>{job.summary && <p>{job.summary}</p>}<a className="admin-button admin-inline-link" href="/admin">通知作成で求人を選ぶ</a></article>)}</div>}
  </AdminRouteFrame>;
}


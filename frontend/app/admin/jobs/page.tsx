"use client";

import { useEffect, useRef, useState } from "react";
import { adminApi, adminErrorMessage, type AdminJobSummary } from "../../lib/admin-api";
import { AdminRouteFrame } from "../AdminRouteFrame";
import { jobStatusLabel } from "../job-status";
import { SelectionModeDialog } from "../SelectionModeDialog";
import { notificationEntryUrl } from "../automatic-workflow";
import { JobDateFilter } from "../JobDateFilter";
import { filterRegisteredJobs, formatJobRegistration } from "../job-registration";
import { LoadingOverlay } from "../LoadingOverlay";

export default function AdminJobsPage() {
  const [pendingJob, setPendingJob] = useState<string | null>(null);
  const [jobs, setJobs] = useState<AdminJobSummary[]>([]);
  const [registeredFrom, setRegisteredFrom] = useState("");
  const visibleJobs = filterRegisteredJobs(jobs, registeredFrom);
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
    <LoadingOverlay active={loading} status="求人一覧を取得中…" />
    <JobDateFilter value={registeredFrom} onChange={setRegisteredFrom} />
    {loading && <div className="admin-info" role="status">求人を読み込んでいます。</div>}
    {error && <div className="admin-error" role="alert"><p>{error}</p><button className="admin-button secondary" type="button" onClick={load}>再読み込み</button></div>}
    {!loading && !error && visibleJobs.length === 0 && <p className="admin-panel-empty">現在表示できる求人はありません。</p>}
    {!loading && !error && visibleJobs.length > 0 && <div className="admin-route-card-list">{visibleJobs.map((job) => <article className="admin-card" key={job.job_id}><div className="selection-item-heading"><h3>{job.title}</h3><span className="state-label">{jobStatusLabel(job.status)}</span></div><dl className="compact-details"><div><dt>求人ID</dt><dd>{job.job_id}</dd></div><div><dt>勤務地</dt><dd>{job.location ?? "未設定"}</dd></div><div><dt>募集人数</dt><dd>{job.openings}名</dd></div><div><dt>登録日（日本時間）</dt><dd>{formatJobRegistration(job.created_at)}</dd></div></dl>{job.summary && <p>{job.summary}</p>}<button className="admin-button" type="button" disabled={job.status !== "published"} onClick={() => setPendingJob(job.job_id)}>通知を作成</button></article>)}</div>}
    {pendingJob && <SelectionModeDialog close={() => setPendingJob(null)} choose={(mode) => { window.location.assign(notificationEntryUrl(mode, pendingJob)); }} />}
  </AdminRouteFrame>;
}


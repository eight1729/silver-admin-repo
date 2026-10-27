"use client";
import { notificationReasonLabel } from "./notification-reasons";
import { useEffect, useRef, useState } from "react";
import { adminApi, adminErrorMessage, type AdminCandidate, type AdminDeliveries, type AdminConfirmation, type AdminJobDetail,
  type AdminJobSummary, type AdminLineSendMode, type AdminMessage, type AdminOperation } from "../lib/admin-api";
import { JobsNavigationGuard } from "./JobsNavigationGuard";
import { messagesEqual, memberSelectionsEqual } from "./notification-ui-state";
import { AdminRouteFrame } from "./AdminRouteFrame";
import { DeliverySummaryPanel } from "./LowerPanels";
import { useLoadingTasks } from "./use-loading-tasks";
import { LoadingOverlay } from "./LoadingOverlay";
import { CandidateSelectionPanel, JobSelectionPanel, MessageEditorPanel } from "./MajorPanels";
import { Modal } from "../components/Modal";
import { AUTO_OPERATION_KEY, notificationEntryUrl } from "./automatic-workflow";
import { canAttemptSend, isLiveMode } from "./send-capability";
import { finalNotificationText } from "./notification-text";
import { notificationNotice, hasUnfilledNotificationFields, createTemplateMessage, DEFAULT_CENTER_DISPLAY_NAME, replaceExactCenterName, replaceExactNotice, type SelectedTemplateId } from "./notification-templates";
import type { CandidateFilterId } from "./candidate-filters";

const emptyMessage = { greeting: "こんにちは。", introduction: "おすすめの求人をご案内します。", note: "" };
const sendAccepted = (op: AdminOperation) => Boolean(op.send_requested_at || ["sending", "completed", "completed_with_errors"].includes(op.status));

export function AutomaticNotification({ initialJobId, resumeOperationId = null }: { initialJobId: string | null; resumeOperationId?: string | null }) {
  const { status: loadingStatus, track } = useLoadingTasks();
  const [jobs, setJobs] = useState<AdminJobSummary[]>([]);
  const [job, setJob] = useState<AdminJobDetail | null>(null);
  const [candidates, setCandidates] = useState<AdminCandidate[]>([]);
  const [selected, setSelected] = useState(new Set<string>());
  const [message, setMessage] = useState<AdminMessage>(emptyMessage);
  const [operation, setOperation] = useState<AdminOperation | null>(null);
  const operationRef = useRef<AdminOperation | null>(null);
  const [confirmation, setConfirmation] = useState<AdminConfirmation | null>(null);
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<"jobs" | "members" | "message" | "review" | "result">("jobs");
  const [capability, setCapability] = useState<AdminLineSendMode | null>(null);
  const [link, setLink] = useState<string | null>(null);
  const [deliveries, setDeliveries] = useState<AdminDeliveries | null>(null);
  const [resultsLoading, setResultsLoading] = useState(false);
  const [resultsError, setResultsError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [jobsError, setJobsError] = useState(false);
  const [filter, setFilter] = useState<CandidateFilterId>("all");
  const [template, setTemplate] = useState<SelectedTemplateId>("standard");
  const [center, setCenter] = useState(DEFAULT_CENTER_DISPLAY_NAME);
  const [notice, setNotice] = useState(emptyMessage.note);
  const [selectedLimit, setSelectedLimit] = useState<number | null>(null);
  const [pendingEntry, setPendingEntry] = useState<string | null>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const appliedCenter = useRef(DEFAULT_CENTER_DISPLAY_NAME);
  const appliedNotice = useRef(emptyMessage.note);
  const [reinclude, setReinclude] = useState(new Set<string>());
  const excluded = useRef(new Set<string>());
  const lock = useRef(false);
  const entryApplied = useRef(false);
  const alive = useRef(true);
  const uncertainTargets = useRef<AdminOperation | null>(null);
  const selectionGeneration = useRef(0);
  const renderedGeneration = selectionGeneration.current;

  function storeOperation(value: AdminOperation) {
    operationRef.current = value;
    if (alive.current) setOperation(value);
    sessionStorage.setItem(AUTO_OPERATION_KEY, value.operation_id); // ID only, never display attributes.
    if (alive.current) window.history.replaceState(null, "", notificationEntryUrl("auto", null, value.operation_id));
  }
  function retainMissing(rows: AdminCandidate[], saved: AdminConfirmation) {
    const known = new Set(rows.map(c => c.member_id));
    return [...rows, ...saved.targets.filter(t => !known.has(t.member_id)).map(t => ({
      member_id: t.member_id, member_number: t.member_number, display_name: t.display_name ?? "取得不可",
      eligible: false, line_linked: false, linkage_unknown: true, reason: "member_no_longer_candidate", selected: true,
    }))];
  }
  async function reloadJobs() {
    try { setJobs(await track("求人一覧を取得中…", () => adminApi.jobs())); setJobsError(false); }
    catch (e) { setJobsError(true); setError(adminErrorMessage(e)); }
  }
  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    const signal = controller.signal;
    void (async () => {
      try {
        const saved = resumeOperationId
          ? await track("通知の状態を取得中…", () => adminApi.operation(resumeOperationId, signal)) : null;
        if (signal.aborted) return;
        if (saved && !saved.automatic_selection) throw new Error("invalid automatic context");
        if (saved && sendAccepted(saved)) {
          // Durable delivery history does not depend on current candidate/linkage availability.
          storeOperation(saved); setSelected(new Set(saved.selected_member_ids)); setMessage(saved.message);
          setPhase("result");
          return;
        }
        const [allJobs, cap] = await Promise.all([track("求人一覧を取得中…", () => adminApi.jobs(signal)), track("送信設定を確認中…", () => adminApi.lineSendMode(signal))]);
        if (signal.aborted) return;
        setJobs(allJobs); setCapability(cap);
        const id = resumeOperationId;
        if (id && saved) {
          const [detail, rows, view] = await Promise.all([track("求人詳細を取得中…", () => adminApi.job(saved.job_id, signal)), track("候補会員とLINE連携状態を確認中…", () => adminApi.candidates(saved.job_id, signal)), track("送信前の確認情報を取得中…", () => adminApi.confirmation(id, signal))]);
          if (signal.aborted) return;
          storeOperation(saved); setJob(detail); setCandidates(retainMissing(rows, view));
          const restoredIds = saved.target_count === 0 && !saved.send_requested_at
            ? (await track("自動選択の対象会員を確認中…", () => adminApi.automaticSelection(saved.job_id, signal))).selected_member_ids : saved.selected_member_ids;
          if (signal.aborted) return;
          setSelected(new Set(restoredIds)); setMessage(saved.message); setNotice(notificationNotice(saved.message));
          setTemplate("custom"); setSelectedLimit(view.selected_recipient_limit); appliedNotice.current = notificationNotice(saved.message); excluded.current = new Set(view.targets.filter(t => t.disposition !== "send").map(t => t.member_id));
          setPhase("message");
          setError("保存済み通知を復元しました。送信前に再検証してください。");
          if (initialJobId && initialJobId !== saved.job_id) {
            if (allJobs.some(item => item.job_id === initialJobId && item.status === "published")) setPendingEntry(initialJobId);
            else setError("指定された求人は選択できません。保存済み通知を保持しています。");
          }
          // Never restore a confirmation token or automatically repeat initial selection.
        }
      } catch (e) { if (!signal.aborted) { setError(adminErrorMessage(e)); setJobsError(true); } }
      finally { if (!signal.aborted) setLoading(false); }
    })();
    return () => { alive.current = false; controller.abort(); };
  }, []);

  useEffect(() => {
    if (loading || jobsError || entryApplied.current || !initialJobId) return;
    entryApplied.current = true;
    if (operationRef.current) return; // Restoring durable work wins over stale URL intent.
    if (!jobs.some(j => j.job_id === initialJobId && j.status === "published")) {
      setError("指定された求人は選択できません。求人一覧から選び直してください。"); return;
    }
    void start(initialJobId);
    // Apply entry intent once; no rerun on subsequent operation/message updates.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialJobId, jobs, jobsError, loading]);

  async function refreshResults() {
    const saved = operationRef.current;
    if (!saved) return;
    setResultsLoading(true); setResultsError("");
    try {
      const [current, result] = await Promise.all([track("通知の状態を取得中…", () => adminApi.operation(saved.operation_id)), track("送信結果を取得中…", () => adminApi.deliveries(saved.operation_id))]);
      if (alive.current) { storeOperation(current); setDeliveries(result); }
    } catch (e) { if (alive.current) setResultsError(adminErrorMessage(e)); }
    finally { if (alive.current) setResultsLoading(false); }
  }
  useEffect(() => {
    if (phase === "result") void refreshResults();
    // Read-only result refresh; never invokes send again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, operation?.operation_id]);

  async function reconcileTargets() {
    const before = uncertainTargets.current;
    if (!before) return;
    const current = await track("保存状態を確認中…", () => adminApi.operation(before.operation_id));
    if (sendAccepted(current)) {
      storeOperation(current); setConfirmation(null); setReinclude(new Set()); setPhase("result");
    } else if (JSON.stringify(current) !== JSON.stringify(before)) {
      // A changed operation is not proof that our PUT succeeded. Recover the latest
      // selection and validate its persisted exclusion latch; never replay old intent.
      await track("保存済み対象を再検証中…", () => adminApi.validate(before.operation_id));
      const checked = await adminApi.operation(before.operation_id);
      const view = await track("送信前の確認情報を取得中…", () => adminApi.confirmation(before.operation_id));
      const latest = await adminApi.operation(before.operation_id);
      if (JSON.stringify(checked) !== JSON.stringify(latest)) throw new Error("selection changed during recovery");
      if (!alive.current) return;
      storeOperation(latest); setSelected(new Set(latest.selected_member_ids));
      if (!messagesEqual(latest.message, before.message)) setMessage(latest.message);
      excluded.current = new Set(view.targets.filter(t => t.disposition !== "send").map(t => t.member_id));
      setReinclude(new Set()); setConfirmation(null); setPhase(sendAccepted(latest) ? "result" : "members");
      selectionGeneration.current++;
    } else {
      // Read the confirmation too, and fence edits made while its attributes resolve.
      await track("送信前の確認情報を取得中…", () => adminApi.confirmation(before.operation_id));
      const latest = await adminApi.operation(before.operation_id);
      if (JSON.stringify(current) !== JSON.stringify(latest)) throw new Error("selection changed during recovery");
      // Nothing was persisted: keep the explicit request and local selection for retry.
    }
    if (alive.current) uncertainTargets.current = null;
  }

  async function persistAndValidate(detail: AdminJobDetail, ids: Set<string>, body: AdminMessage, explicit: Set<string>) {
    if (uncertainTargets.current) {
      await reconcileTargets();
      throw new Error("review recovered selection before retry");
    }
    if (!ids.size || detail.status !== "published") throw new Error("no sendable selection");
    let op = operationRef.current;
    if (!op) {
      op = await track("通知を作成中…", () => adminApi.createOperation({ job_id: detail.job_id, notification_type: "new_job_match", automatic_selection: true, ...body }));
      storeOperation(op); // Keep partial success so retry never creates another operation.
    }
    const applied = [...explicit].filter(id => ids.has(id));
    let savedTargets: AdminOperation;
    try {
      savedTargets = await track("対象会員を保存中…", () => adminApi.updateTargets(op.operation_id, [...ids], applied));
    } catch (e) {
      uncertainTargets.current = op;
      await reconcileTargets();
      throw e; // Reconciliation is never reported as successful saving or confirmation.
    }
    storeOperation(savedTargets);
    applied.forEach(id => excluded.current.delete(id));
    setReinclude(values => new Set([...values].filter(id => !applied.includes(id))));
    selectionGeneration.current++;
    const savedBody = await track("通知文を保存中…", () => adminApi.updateOperation(op.operation_id, body));
    storeOperation(savedBody);
    await track("送信前の検証中…", () => adminApi.validate(op.operation_id));
    const [current, view, cap, targetLink] = await Promise.all([
      track("通知の状態を取得中…", () => adminApi.operation(op.operation_id)), track("送信前の確認情報を取得中…", () => adminApi.confirmation(op.operation_id)), track("送信設定を確認中…", () => adminApi.lineSendMode()), track("求人リンクを取得中…", () => adminApi.notificationLink(detail.job_id)),
    ]);
    if (!alive.current) return;
    storeOperation(current); setConfirmation(view); setSelectedLimit(view.selected_recipient_limit); setCapability(cap); setLink(targetLink.url);
    setCandidates(rows => retainMissing(rows, view));
    excluded.current = new Set(view.targets.filter(t => t.disposition !== "send").map(t => t.member_id));
    setReinclude(new Set()); setPhase(hasUnfilledNotificationFields(body) ? "message" : "review"); setOpen(!hasUnfilledNotificationFields(body));
  }

  async function start(id: string) {
    if (lock.current || operationRef.current) return;
    lock.current = true; setBusy(true); setError(""); setConfirmation(null);
    try {
      const [detail, rows, choice] = await Promise.all([track("求人詳細を取得中…", () => adminApi.job(id)), track("候補会員とLINE連携状態を確認中…", () => adminApi.candidates(id)), track("自動選択の対象会員を確認中…", () => adminApi.automaticSelection(id))]);
      if (!alive.current) return;
      if (detail.status !== "published") throw new Error("job is not published");
      const summary = jobs.find(j => j.job_id === id);
      const body = createTemplateMessage("standard", center, { title: detail.title, description: detail.description, location: detail.location,
        summary: summary?.summary, workDays: summary?.work_days, workTime: summary?.work_time }, emptyMessage.note);
      const ids = new Set(choice.selected_member_ids);
      setJob(detail); setCandidates(rows); setSelected(ids); setMessage(body); setPhase("members");
      if (!ids.size) { setPhase("jobs"); setError(choice.reason ?? "自動選択対象がいません。"); return; }
      await persistAndValidate(detail, ids, body, new Set());
    } catch (e) { if (alive.current) setError(adminErrorMessage(e)); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }

  async function saveAndReview() {
    if (!job || lock.current || !selected.size || renderedGeneration !== selectionGeneration.current || (operationRef.current && sendAccepted(operationRef.current))) return;
    lock.current = true; setBusy(true); setError(""); setConfirmation(null); setOpen(false);
    try { await persistAndValidate(job, selected, message, reinclude); }
    catch (e) { if (alive.current) setError(`${adminErrorMessage(e)} 保存状態を確認し、除外者を戻す場合は会員を選び直してください。`); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }

  function edit(next: "members" | "message") { setOpen(false); setConfirmation(null); setPhase(next); }
  const limit = selectedLimit;
  const capLimit = capability?.max_recipients ?? null;
  const effectiveLimit = limit === null ? capLimit : capLimit === null ? limit : Math.min(limit, capLimit);
  const confirmationText = confirmation ? finalNotificationText(confirmation.message, link, capability) : null;
  const canSend = Boolean(confirmation && !hasUnfilledNotificationFields(confirmation.message) && confirmationText !== null && confirmationText.length <= 5000 && confirmation?.can_send && confirmation.confirmation_token && !confirmation.requires_revalidation
    && canAttemptSend(capability, confirmation.sendable_count) && (!isLiveMode(capability) || link) && !busy);
  async function send() {
    if (!confirmation?.confirmation_token || !canSend || lock.current) return;
    const confirmationToken = confirmation.confirmation_token;
    lock.current = true; setBusy(true); setError("");
    try {
      const sent = await track("通知を送信中…", () => adminApi.send(confirmation.operation_id, confirmationToken));
      storeOperation(sent); setOpen(false); setConfirmation(null); setPhase("result");
    } catch (e) {
      setOpen(false); setConfirmation(null); setPhase("message");
      setError(`${adminErrorMessage(e)} 送信結果を確認し、未送信の場合だけ再検証してください。`);
      // A network error may follow an accepted reservation. Read before offering another send.
      try {
        const current = await track("通知の状態を取得中…", () => adminApi.operation(confirmation.operation_id)); storeOperation(current);
        if (sendAccepted(current)) setPhase("result");
      } catch { /* Token remains discarded. No automatic resend. */ }
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }

  return <AdminRouteFrame title="通知作成：自動選択" description="初期選択は評価5・LINE連携済み・会員番号降順の最大100人です。">
    <JobsNavigationGuard busy={loading || busy || loadingStatus !== null || operation?.status === "sending"} dirty={Boolean(job && (!operation || !messagesEqual(message, operation.message) || !memberSelectionsEqual(selected, operation.selected_member_ids ?? []) || notice.trim() !== appliedNotice.current || center.trim() !== appliedCenter.current))} />
    <LoadingOverlay active={loading || busy || loadingStatus !== null} status={loadingStatus ?? "通知作成を準備中…"} />
    {error && <p className="admin-error" role="alert">{error}</p>}
    {!operation && <JobSelectionPanel jobs={jobs} selectedJobId={job?.job_id ?? null} selectedJob={job} loading={loading} error={jobsError} busy={busy}
      retry={() => void reloadJobs()} select={start} />}
    {job && phase === "members" && <>
      <p>選択済みを上部に表示します。除外者を戻す場合はチェックを一度解除して再選択してください。初期100人上限は編集後には適用されません。</p>
      <CandidateSelectionPanel submitLabel="保存・再検証して最終確認へ" job={job} candidates={candidates} selected={selected}
        notificationType="new_job_match" notificationTypeLocked setNotificationType={() => {}} filter={filter} setFilter={setFilter}
        toggle={(id) => { if (busy || lock.current || uncertainTargets.current || renderedGeneration !== selectionGeneration.current) return; const next = new Set(selected); if (next.has(id)) next.delete(id); else {
          next.add(id); if (excluded.current.has(id)) setReinclude(values => new Set([...values, id]));
        } selectionGeneration.current++; setSelected(next); setConfirmation(null); }}
        begin={saveAndReview} busy={busy} error={false} retry={async () => setCandidates(await track("候補会員とLINE連携状態を確認中…", () => adminApi.candidates(job.job_id)))}
        targetsPending={Boolean(operation)} maxRecipients={effectiveLimit} editable />
    </>}
    {job && operation && phase === "message" && <>
      <MessageEditorPanel job={job} message={message} setMessage={value => { setMessage(value); setConfirmation(null); setTemplate("custom"); }}
        selectedTemplate={template} applyTemplate={value => { if (value === "custom") return; setTemplate(value); setMessage(createTemplateMessage(value, center, { title: job.title, description: job.description, location: job.location, workDays: jobs.find(item => item.job_id === job.job_id)?.work_days, workTime: jobs.find(item => item.job_id === job.job_id)?.work_time }, notice)); setConfirmation(null); }}
        centerDisplayNameDraft={center} setCenterDisplayNameDraft={setCenter} noticeDraft={notice} setNoticeDraft={setNotice}
        applyEditorFields={() => {
          setMessage(replaceExactNotice(replaceExactCenterName(message, appliedCenter.current, center.trim()), appliedNotice.current, notice.trim()));
          appliedCenter.current = center.trim(); appliedNotice.current = notice.trim(); setConfirmation(null);
        }} editorFieldsChanged={notice.trim() !== appliedNotice.current || center.trim() !== appliedCenter.current}
        busy={busy} validationStale lineSendMode={capability} notificationLink={link} />
      <button className="admin-button" disabled={busy || !selected.size} onClick={() => void saveAndReview()}>保存・再検証して最終確認へ</button>
      <button className="admin-button secondary" disabled={busy} onClick={() => edit("members")}>会員を選択</button>
    </>}
    {phase === "review" && confirmation && <button className="admin-button" onClick={() => setOpen(true)}>最終確認を表示</button>}
    {phase === "result" && <><p role="status">送信受付状態：{operation?.status}。送信を自動で繰り返しません。</p>
      <DeliverySummaryPanel operation={operation} deliveries={deliveries} loading={resultsLoading} error={resultsError} retry={refreshResults} />
      <button className="admin-button secondary" disabled={resultsLoading} onClick={() => void refreshResults()}>配信結果を更新</button>
      <button className="admin-button" disabled={busy || loadingStatus !== null || resultsLoading || !operation || !["completed", "completed_with_errors"].includes(operation.status)} onClick={() => {
        if (!lock.current && loadingStatus === null && !resultsLoading && operation && ["completed", "completed_with_errors"].includes(operation.status)) window.location.assign("/admin/jobs");
      }}>求人を変更して新規作成</button></>}
    {pendingEntry && <Modal placement="center" title="選択した求人で新しい通知を作成しますか？" onClose={() => { setPendingEntry(null); window.history.replaceState(null, "", notificationEntryUrl("auto", null, operation?.operation_id)); }} footer={<>
      <button className="admin-button secondary" onClick={() => { setPendingEntry(null); window.history.replaceState(null, "", notificationEntryUrl("auto", null, operation?.operation_id)); }}>保存済み通知へ戻る</button>
      <button className="admin-button" onClick={() => { sessionStorage.removeItem(AUTO_OPERATION_KEY); window.location.assign(notificationEntryUrl("auto", pendingEntry)); }}>選択した求人で作成</button>
    </>}><p>保存済み通知は削除しません。求人一覧で選んだ求人へ切り替え、新しい通知を作成します。</p></Modal>}
    {operation && <button className="admin-button secondary" disabled={busy || resultsLoading || operation.status === "sending"} onClick={() => setResetOpen(true)}>新しい通知を作成</button>}
    {resetOpen && <Modal title="新しい通知を作成しますか？" onClose={() => setResetOpen(false)} footer={<>
      <button className="admin-button secondary" onClick={() => setResetOpen(false)}>戻る</button>
      <button className="admin-button" onClick={() => { sessionStorage.removeItem(AUTO_OPERATION_KEY); window.location.assign("/admin?mode=auto"); }}>新しい通知へ</button>
    </>}><p>保存済みの通知は削除しません。送信済みの場合は、同じ内容を重複送信しないよう結果を確認してください。</p></Modal>}
    <p><a className="admin-link" href="/admin?mode=manual">マニュアル選択へ</a>　<a className="admin-link" href="/admin/jobs">求人一覧へ</a></p>
    {open && confirmation && <Modal placement="center" title="送信前の最終確認" onClose={() => { if (!busy) setOpen(false); }} footer={<>
      <button className="admin-button" disabled={!canSend} onClick={() => void send()}>{confirmation.excluded_count > 0 ? `除外理由を確認して送信可能な${confirmation.sendable_count}名に送信` : "送信"}</button>
      <button className="admin-button secondary" disabled={busy} onClick={() => edit("members")}>会員を選択</button>
      <button className="admin-button secondary" disabled={busy} onClick={() => edit("message")}>通知文編集</button>
    </>}>
      <div className="automatic-message">{finalNotificationText(confirmation.message, link, capability) ?? "リンク・送信設定の確認待ち"}</div>
      <p>初期選択：{confirmation.initial_count}人 ／ 現在選択：{confirmation.selected_count}人</p>
      <p>送信可能：{confirmation.sendable_count}人 ／ 除外：{confirmation.excluded_count}人</p>
      {confirmation.selected_recipient_limit != null && <p>この環境の選択上限：{confirmation.selected_recipient_limit}人</p>}
      {capLimit != null && <p>LINE capability上限：{capLimit}人</p>}
      {!canSend && <p role="alert">送信条件を満たしていません。送信制限・検証結果を確認し、編集後に再検証してください。</p>}
      {([true, false] as const).map(sendable => <section key={String(sendable)}><h3>{sendable ? "送信可能会員" : "除外会員"}</h3>
        <ul className="automatic-recipient-list">{confirmation.targets.filter(t => (t.disposition === "send") === sendable).map(t => <li key={t.member_id}>
          {t.member_number ?? "番号未取得"}・{t.display_name ?? "氏名取得不可"}・携帯下4桁：{t.mobile_phone_last4 ?? "未登録"}
          {!sendable && <span> ／ {notificationReasonLabel(t.reason)}</span>}
        </li>)}</ul></section>)}
    </Modal>}
  </AdminRouteFrame>;
}

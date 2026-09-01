import { useEffect, useRef, useState } from "react";
import type {
  AdminCandidate,
  AdminJobDetail,
  AdminJobSummary,
  AdminLineSendMode,
  AdminMessage,
  AdminOperation,
  AdminValidation,
  NotificationType,
} from "../lib/admin-api";
import { formatBlockingReasons } from "./blocking-reasons";
import { candidateFilters, filterCandidates, type CandidateFilterId } from "./candidate-filters";
import { CENTER_DISPLAY_NAME_MAX_LENGTH, composeAdminMessage, notificationBody, notificationNotice, notificationTemplates, type SelectedTemplateId } from "./notification-templates";
import { uiStatePresentation, type NotificationUiState, type WorkflowAction } from "./notification-ui-state";

export function CandidateFilterMenu({ value, onChange }: { value: CandidateFilterId; onChange: (value: CandidateFilterId) => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: MouseEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => { document.removeEventListener("mousedown", closeOutside); document.removeEventListener("keydown", closeOnEscape); };
  }, [open]);
  const current = candidateFilters.find((item) => item.id === value)?.label;
  return <div className="candidate-filter-menu" ref={root}><button type="button" className="admin-button secondary compact candidate-filter-trigger" aria-expanded={open} aria-controls="candidate-filter-options" onClick={() => setOpen((currentOpen) => !currentOpen)}><span aria-hidden="true">⌁</span>{value === "all" ? "条件で絞り込み" : current}</button>{open && <div className="candidate-filter-popover" id="candidate-filter-options" role="menu" aria-label="候補会員の絞り込み条件">{candidateFilters.map((item) => <button type="button" role="menuitemradio" aria-checked={item.id === value} className={item.id === value ? "is-current" : ""} onClick={() => { onChange(item.id); setOpen(false); }} key={item.id}>{item.label}<span aria-hidden="true">{item.id === value ? "✓" : ""}</span></button>)}</div>}</div>;
}

export function JobSelectionPanel({ jobs, selectedJobId, selectedJob, loading, error, busy, retry, select }: {
  jobs: AdminJobSummary[];
  selectedJobId: string | null;
  selectedJob: AdminJobDetail | null;
  loading: boolean;
  error: boolean;
  busy: boolean;
  retry: () => void;
  select: (id: string) => Promise<void>;
}) {
  return <div className="major-panel-content">
    {loading && <div className="admin-info" role="status">求人を読み込んでいます。</div>}
    {!loading && error && <div className="admin-error" role="alert"><p>求人一覧を取得できませんでした。</p><button className="admin-button secondary" type="button" onClick={retry}>求人一覧を再読み込み</button></div>}
    {!loading && !error && jobs.length === 0 && <div className="admin-panel-empty">現在選択できる求人はありません。</div>}
    {!loading && !error && jobs.length > 0 && <><div className="job-selection-table-wrapper"><table className="job-selection-table"><colgroup><col className="job-select-column"/><col className="job-name-column"/><col className="job-days-column"/><col className="job-time-column"/><col className="job-summary-column"/></colgroup><thead><tr><th scope="col"><span className="sr-only">選択</span></th><th scope="col">求人名</th><th scope="col">勤務日</th><th scope="col">勤務時間</th><th scope="col">概要</th></tr></thead><tbody>{jobs.map((item) => {
        const selected = item.job_id === selectedJobId;
        const selectable = item.status === "published";
        const disabled = busy || !selectable;
        return <tr className={`${selected ? "is-selected" : ""}${!selectable ? " is-disabled" : ""}`} key={item.job_id} onClick={() => { if (!disabled && !selected) void select(item.job_id); }}><td><input type="radio" name="admin-selected-job" checked={selected} disabled={disabled} aria-label={`${item.title}を選択`} onClick={(event) => event.stopPropagation()} onChange={() => { if (!disabled && !selected) void select(item.job_id); }}/></td><th scope="row">{item.title}</th><td>{item.work_days || "—"}</td><td>{item.work_time || "—"}</td><td><span className="job-summary-clamp">{item.summary || "—"}</span></td></tr>;
      })}</tbody></table></div><div className="job-list-link-row"><a className="admin-link" href="/admin/jobs">求人一覧へ <span aria-hidden="true">↗</span></a></div></>}
  </div>;
}

export function CandidateSelectionPanel({ job, candidates, selected, notificationType, setNotificationType, toggle, begin, busy, error, retry, targetsPending, singleRecipient, editable, filter, setFilter }: {
  job: AdminJobDetail;
  candidates: AdminCandidate[];
  selected: Set<string>;
  notificationType: NotificationType;
  setNotificationType: (value: NotificationType) => void;
  toggle: (id: string) => void;
  begin: () => Promise<void>;
  busy: boolean;
  error: boolean;
  retry: () => Promise<void>;
  targetsPending: boolean;
  singleRecipient: boolean;
  editable: boolean;
  filter: CandidateFilterId;
  setFilter: (value: CandidateFilterId) => void;
}) {
  const pageSize = 5;
  const [page, setPage] = useState(1);
  useEffect(() => { setFilter("all"); setPage(1); }, [job.job_id, setFilter]);
  useEffect(() => setPage(1), [filter]);
  const visibleCandidates = filterCandidates(candidates, filter);
  const totalPages = Math.max(1, Math.ceil(visibleCandidates.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const pageCandidates = visibleCandidates.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const hiddenSelected = candidates.filter((candidate) => selected.has(candidate.member_id) && !visibleCandidates.some((visible) => visible.member_id === candidate.member_id));
  return <div className="major-panel-content">
    {busy && candidates.length === 0 && <div className="admin-info" role="status">候補会員を読み込んでいます。</div>}
    {error && <div className="admin-error" role="alert"><p>候補会員を取得できませんでした。</p><button className="admin-button secondary" type="button" disabled={busy} onClick={() => void retry()}>候補会員を再読み込み</button></div>}
    {!busy && !error && candidates.length === 0 && <div className="admin-panel-empty">この求人に表示できる候補会員はいません。</div>}
    {hiddenSelected.length > 0 && <div className="admin-info" role="status"><p>選択中の会員は現在の絞り込み結果には表示されていません。</p><ul>{hiddenSelected.map((candidate) => <li key={candidate.member_id}>{candidate.display_name}</li>)}</ul></div>}
    {candidates.length > 0 && visibleCandidates.length === 0 && <div className="admin-panel-empty">現在の条件に一致する候補会員はいません。</div>}
    {pageCandidates.length > 0 && <div className="candidate-table-wrapper"><table className="candidate-selection-table"><colgroup><col className="candidate-select-column"/><col className="candidate-id-column"/><col className="candidate-name-column"/><col className="candidate-preference-column"/><col className="candidate-line-column"/><col className="candidate-eligible-column"/></colgroup><thead><tr><th scope="col"><span className="sr-only">選択</span></th><th scope="col">会員ID</th><th scope="col">氏名</th><th scope="col">希望条件</th><th scope="col">LINE連携</th><th scope="col">通知可否</th></tr></thead><tbody>
      {pageCandidates.map((candidate) => {
        const isSelected = selected.has(candidate.member_id);
        const limitReached = singleRecipient && selected.size >= 1 && !isSelected;
        const disabled = !editable || !candidate.eligible || limitReached || busy;
        return <tr className={`${isSelected ? "is-selected" : ""}${disabled && !isSelected ? " is-disabled" : ""}`} key={candidate.member_id} onClick={() => { if ((!disabled || isSelected) && !busy) toggle(candidate.member_id); }}>
          <td><input type="radio" name="admin-selected-candidate" checked={isSelected} disabled={disabled} aria-label={`${candidate.display_name}を選択`} aria-describedby={`candidate-state-${candidate.member_id}`} onClick={(event) => event.stopPropagation()} onChange={() => { if (!disabled && !isSelected) toggle(candidate.member_id); }}/></td>
          <th scope="row">{candidate.member_id}</th><td>{candidate.display_name || "—"}</td><td><span className="candidate-preference-clamp">{candidate.preference_summary || "—"}</span></td><td><span className={`candidate-state-badge ${candidate.line_linked ? "is-positive" : "is-neutral"}`}>{candidate.line_linked ? "連携済み" : "未連携"}</span></td><td><span id={`candidate-state-${candidate.member_id}`} className={`candidate-state-badge ${candidate.eligible ? "is-positive" : "is-negative"}`}>{candidate.eligible ? "通知可能" : "通知不可"}</span>{candidate.reason && <span className="sr-only">{safeReasonLabel(candidate.reason)}</span>}{limitReached && <span className="sr-only">1名選択済み</span>}</td>
        </tr>;
      })}
    </tbody></table></div>}
    {visibleCandidates.length > 0 && <div className="candidate-pagination" aria-label="候補会員のページ切り替え"><span>{(currentPage - 1) * pageSize + 1}〜{Math.min(currentPage * pageSize, visibleCandidates.length)} / {visibleCandidates.length}件</span><div><button type="button" className="admin-button secondary compact" disabled={currentPage === 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>前へ</button>{Array.from({ length: totalPages }, (_, index) => index + 1).map((pageNumber) => <button type="button" className={`candidate-page-button${pageNumber === currentPage ? " is-current" : ""}`} aria-current={pageNumber === currentPage ? "page" : undefined} onClick={() => setPage(pageNumber)} key={pageNumber}>{pageNumber}</button>)}<button type="button" className="admin-button secondary compact" disabled={currentPage === totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))}>次へ</button></div></div>}
    <div className="candidate-list-link-row"><a className="admin-link" href={`/admin/members?jobId=${encodeURIComponent(job.job_id)}`}>会員一覧へ <span aria-hidden="true">↗</span></a></div>
    {editable && <><div className="candidate-footer-actions"><label><span>通知種別</span><select value={notificationType} onChange={(event) => setNotificationType(event.target.value as NotificationType)}><option value="new_job_match">新着求人マッチ</option><option value="existing_job_match">既存求人マッチ</option><option value="custom_job">個別求人</option></select></label><button className="admin-button candidate-primary-compact" type="button" disabled={busy || selected.size === 0 || (singleRecipient && selected.size !== 1) || job.status !== "published"} onClick={() => void begin()}>{busy ? "対象を保存中…" : targetsPending ? "対象会員の保存を再試行" : "対象を保存して通知文編集へ"}</button></div>
      {targetsPending && <div className="admin-info" role="status">operationは作成済みです。対象会員の保存を再試行してください。</div>}
      {singleRecipient && <p className="candidate-limit-note" role="note">実LINE検証では1名だけ選択できます。選択済みの会員を解除すると別の会員を選べます。</p>}</>}
    {!editable && <p className="panel-guidance">対象を変更する場合は、送信前確認から「対象変更」を選択してください。</p>}
  </div>;
}

export function MessageEditorPanel({ job, message, setMessage, selectedTemplate, applyTemplate, centerDisplayNameDraft, setCenterDisplayNameDraft, noticeDraft, setNoticeDraft, applyEditorFields, editorFieldsChanged, busy, validationStale, lineSendMode, notificationLink }: {
  job: AdminJobDetail;
  message: AdminMessage;
  setMessage: (value: AdminMessage) => void;
  selectedTemplate: SelectedTemplateId;
  applyTemplate: (value: SelectedTemplateId) => void;
  centerDisplayNameDraft: string;
  setCenterDisplayNameDraft: (value: string) => void;
  noticeDraft: string;
  setNoticeDraft: (value: string) => void;
  applyEditorFields: () => void;
  editorFieldsChanged: boolean;
  busy: boolean;
  validationStale: boolean;
  lineSendMode: AdminLineSendMode | null;
  notificationLink: string | null;
}) {
  const body = notificationBody(message);
  const valid = Object.values(message).every((value) => value.trim());
  const liveReady = lineSendMode?.mode === "staging_live" && lineSendMode.ready === true;
  const canonicalLink = liveReady ? notificationLink : job.job_url;
  return <div className="major-panel-content">
    <div className="notification-message-heading"><label htmlFor="notification-body">通知メッセージ</label><select aria-label="通知テンプレート" value={selectedTemplate} disabled={busy} onChange={(event) => applyTemplate(event.target.value as SelectedTemplateId)}><option value="custom" disabled>カスタム</option>{notificationTemplates.map((template) => <option value={template.id} key={template.id} disabled={template.requiresJob && !job}>{template.label}</option>)}</select></div>
    <div className="notification-body-field"><textarea id="notification-body" value={body} onChange={(event) => setMessage(composeAdminMessage(event.target.value, message.note))} aria-describedby="notification-body-count" /><small id="notification-body-count" aria-live="polite">{body.length}文字</small></div>
    <div className="compact-editor-field"><span>求人リンク</span><output className="readonly-canonical-url">{canonicalLink ? <a href={canonicalLink} target="_blank" rel="noreferrer">{canonicalLink}</a> : "求人リンクを準備しています"}</output></div>
    <div className="compact-editor-field"><label htmlFor="center-display-name">センター名</label><input id="center-display-name" value={centerDisplayNameDraft} maxLength={CENTER_DISPLAY_NAME_MAX_LENGTH} onChange={(event) => setCenterDisplayNameDraft(event.target.value)} /></div>
    <div className="compact-editor-field"><label htmlFor="notification-note">注意事項</label><textarea id="notification-note" className="notification-note" value={noticeDraft} onChange={(event) => setNoticeDraft(event.target.value)} aria-describedby="notification-note-count"/><small id="notification-note-count" aria-live="polite">{noticeDraft.length}文字</small></div>
    <div className="editor-reflect-actions"><button className="admin-button secondary compact" type="button" disabled={busy || !centerDisplayNameDraft.trim() || !editorFieldsChanged} onClick={applyEditorFields}>本文へ反映</button></div>
    <p className="system-supplied-note"><strong>システム付与:</strong> {liveReady ? lineSendMode.message_prefix ?? "検証表示を確認中" : lineSendMode?.mode === "staging_live" ? "実LINE送信ブロック中" : "Fake送信（実LINE送信なし）"}。求人リンクと安全文言は編集できません。</p>
    {validationStale && <p className="validation-state is-stale" role="status">内容が変更されたため、再検証が必要です。</p>}
    {!valid && <p className="field-help-error" role="alert">通知メッセージを入力してください。</p>}
  </div>;
}

export function MessageReadOnlySummary({ message, edit }: { message: AdminMessage; edit?: () => void }) {
  const notice = notificationNotice(message);
  return <div className="message-readonly"><dl><div><dt>通知メッセージ</dt><dd>{notificationBody(message)}</dd></div>{notice && <div><dt>注意事項</dt><dd>{notice}</dd></div>}</dl>{edit && <div className="message-readonly-actions"><button className="admin-button secondary" type="button" onClick={edit}><span aria-hidden="true">✎</span>通知文編集</button></div>}</div>;
}

export function SendConfirmationPanel({ operation, validation, candidates, selected, save, send, revalidate, busy, canSaveDraft, canValidate, canSend, validationCurrent, action, targets, lineSendMode, queueFailure }: {
  operation: AdminOperation;
  validation: AdminValidation;
  candidates: AdminCandidate[];
  selected: Set<string>;
  save: () => Promise<void>;
  send: () => Promise<void>;
  revalidate: () => Promise<void>;
  busy: boolean;
  canSaveDraft: boolean;
  canValidate: boolean;
  canSend: boolean;
  validationCurrent: boolean;
  action: WorkflowAction;
  targets: () => void;
  lineSendMode: AdminLineSendMode | null;
  queueFailure: boolean;
}) {
  return <div className="compact-send-confirmation">
    <SendOverview operation={operation} validation={validation} candidates={candidates} selected={selected} validationCurrent={validationCurrent} action={action} lineSendMode={lineSendMode} queueFailure={queueFailure} />
    <div className="confirmation-edit-links"><button type="button" disabled={busy} onClick={targets}>対象を変更</button></div>
    <SendActionButtons operation={operation} save={save} validate={revalidate} send={send} canSaveDraft={canSaveDraft} canValidate={canValidate} canSend={canSend} action={action} busy={busy} />
  </div>;
}

export function SendPreparationState({ operation, validation, candidates, selected, save, validate, canSaveDraft, canValidate, busy, action, validationCurrent, lineSendMode }: { operation: AdminOperation | null; validation: AdminValidation | null; candidates: AdminCandidate[]; selected: Set<string>; save: () => Promise<void>; validate: () => Promise<void>; canSaveDraft: boolean; canValidate: boolean; busy: boolean; action: WorkflowAction; validationCurrent: boolean; lineSendMode: AdminLineSendMode | null }) {
  return <div className="compact-send-confirmation">
    <SendOverview operation={operation} validation={validation} candidates={candidates} selected={selected} validationCurrent={validationCurrent} action={action} lineSendMode={lineSendMode} queueFailure={false} />
    <SendActionButtons operation={operation} save={save} validate={validate} canSaveDraft={canSaveDraft} canValidate={canValidate} canSend={false} action={action} busy={busy} />
  </div>;
}

function SendOverview({ operation, validation, candidates, selected, validationCurrent, action, lineSendMode, queueFailure }: { operation: AdminOperation | null; validation: AdminValidation | null; candidates: AdminCandidate[]; selected: Set<string>; validationCurrent: boolean; action: WorkflowAction; lineSendMode: AdminLineSendMode | null; queueFailure: boolean }) {
  const selectedCount = operation?.selected_count ?? selected.size;
  const unlinkedCount = candidates.filter((candidate) => selected.has(candidate.member_id) && candidate.line_linked === false).length;
  const validating = action === "validating";
  const hasProblem = !validating && (queueFailure || !operation || selectedCount === 0 || validation !== null && !validationCurrent || validation?.can_proceed === false || validation?.sendable_count === 0 || lineSendMode?.mode === "staging_live" && lineSendMode.ready !== true);
  const validated = !validating && validation !== null && validationCurrent && validation.can_proceed && !hasProblem;
  const problems = new Set<string>();
  if (selectedCount === 0) problems.add("対象会員が選択されていません。");
  if (!operation) problems.add("通知本文を保存してください。");
  if (validation && !validationCurrent) problems.add("内容が変更されたため再検証が必要です。");
  if (unlinkedCount > 0) problems.add("LINE未連携のため送信できない対象があります。");
  if (validationCurrent && validation?.sendable_count === 0) problems.add("送信可能な対象者がいません。");
  if (lineSendMode?.mode === "staging_live" && lineSendMode.ready !== true) {
    const reasons = formatBlockingReasons(lineSendMode);
    if (reasons.length) reasons.forEach((reason) => problems.add(reason));
    else problems.add("送信モードが利用できません。");
  }
  if (queueFailure) problems.add("送信処理は開始されていません。自動再送は行いません。");
  if (validationCurrent) validation?.reasons.forEach((reason) => problems.add(safeReasonLabel(reason)));
  const result = validating ? { icon: "…", text: "検証中", className: "is-pending" }
    : validated ? { icon: "✓", text: "問題ありません", className: "is-success" }
      : hasProblem ? { icon: "×", text: "問題があります", className: "is-problem" }
        : { icon: "○", text: "検証してください", className: "is-pending" };
  return <>
    <dl className="send-overview-list">
      <div><dt>対象会員数</dt><dd>{selectedCount}名</dd></div>
      <div><dt>LINE未連携数</dt><dd>{candidates.length || selectedCount === 0 ? `${unlinkedCount}名` : "—"}</dd></div>
      <div><dt>送信対象会員数</dt><dd>{validation && validationCurrent ? `${validation.sendable_count}名` : "—"}</dd></div>
      <div><dt>検証結果</dt><dd className={`send-validation-result ${result.className}`} role={validating ? "status" : undefined}><span aria-hidden="true">{result.icon}</span>{result.text}</dd></div>
    </dl>
    {problems.size > 0 && <div className="send-problem-details" role="alert"><strong>問題の詳細</strong><ul>{[...problems].map((problem) => <li key={problem}>{problem}</li>)}</ul></div>}
  </>;
}

function SendActionButtons({ operation, save, validate, send, canSaveDraft, canValidate, canSend, action, busy }: { operation: AdminOperation | null; save: () => Promise<void>; validate: () => Promise<void>; send?: () => Promise<void>; canSaveDraft: boolean; canValidate: boolean; canSend: boolean; action: WorkflowAction; busy: boolean }) {
  return <div className="compact-send-actions">
    <p className="compact-send-warning"><span aria-hidden="true">!</span> 送信後は取り消せません。実LINE検証は送信可能な1名に限定されます。</p>
    <div className="compact-send-secondary"><button className="admin-button secondary" type="button" disabled={!canSaveDraft} onClick={() => void save()}>{action === "saving" ? "保存中…" : "下書き保存"}</button><button className="admin-button secondary" type="button" disabled={!canValidate} onClick={() => void validate()}>{action === "validating" ? "検証中…" : "検証"}</button></div>
    <button className="admin-button send-primary compact-send-primary" type="button" disabled={!canSend || !send} onClick={() => { if (send) void send(); }}>{action === "sending" ? "送信処理中…" : "送信実行"}<svg aria-hidden="true" viewBox="0 0 24 24" width="17" height="17"><path d="m3 3 18 9-18 9 4-9-4-9Zm4.7 8h7.8L6.1 6.3 7.7 11Zm-1.6 6.7 9.4-4.7H7.7l-1.6 4.7Z" fill="currentColor"/></svg></button>
    {!canSend && !busy && operation && <p className="compact-disabled-reason">送信には最新の検証結果と送信可能な対象者が必要です。</p>}
  </div>;
}

export function WorkflowStateNotice({ state, reason }: { state: NotificationUiState; reason?: string | null }) {
  const presentation = uiStatePresentation(state);
  return <div className={`workflow-state workflow-state--${state}`} role="status"><strong>{presentation.label}</strong><span>{reason ?? presentation.description}</span></div>;
}

function jobStatusLabel(status: string) { return ({ published: "募集中", closed: "募集終了", draft: "下書き", suspended: "停止中" } as Record<string, string>)[status] ?? "状態不明"; }
function safeReasonLabel(reason: string) { return ({ line_not_linked: "LINE未連携", not_selected: "未選択", member_ineligible: "通知対象外", job_closed: "求人募集終了", job_version_changed: "求人情報更新あり", recipient_unavailable: "送信先を利用できません", line_temporary_error: "一時的な送信エラー", line_unknown_result: "送信結果不明" } as Record<string, string>)[reason] ?? "条件を確認してください"; }

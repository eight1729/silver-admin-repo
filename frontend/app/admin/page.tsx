"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  adminApi, adminErrorMessage, type AdminCandidate, type AdminDeliveries,
  AdminApiError,
  type AdminJobDetail, type AdminJobSummary, type AdminMessage,
  type AdminLineSendMode, type AdminOperation, type AdminValidation, type NotificationType,
} from "../lib/admin-api";
import { ADMIN_HOME_EVENT } from "./AdminHomeButton";
import { useAdminEnvironment } from "./AdminEnvironment";
import { clearedTransientAdminState, createOrSaveTargets, reloadDeliveryResults, restoreAdminOperation, saveThenValidate, sendThenLoadDeliveries } from "./admin-workflow";
import { AdminPanel } from "./AdminPanel";
import { AdminShell } from "./AdminShell";
import { CandidateFilterMenu, CandidateSelectionPanel, JobSelectionPanel, MessageEditorPanel, MessageReadOnlySummary, SendConfirmationPanel, SendPreparationState } from "./MajorPanels";
import type { CandidateFilterId } from "./candidate-filters";
import { createValidationSnapshot, deriveNotificationUiState, isValidationSnapshotCurrent, memberSelectionsEqual, messagesEqual, type ValidationInput, type ValidationSnapshot, type WorkflowAction } from "./notification-ui-state";
import { CENTER_DISPLAY_NAME_MAX_LENGTH, DEFAULT_CENTER_DISPLAY_NAME, createTemplateMessage, notificationNotice, notificationTemplates, replaceExactCenterName, replaceExactNotice, type NotificationTemplateJob, type SelectedTemplateId } from "./notification-templates";
import { DeliverySummaryPanel, RecentOperationHistory } from "./LowerPanels";
import { Modal } from "../components/Modal";
import type { SessionHistoryEvent } from "./operation-history";
import { ADMIN_OPERATION_STORAGE_KEY, ADMIN_SELECTED_MEMBERS_STORAGE_KEY } from "./admin-session";

type Step = "jobs" | "detail" | "edit" | "confirm" | "result";
const STORAGE_KEY = ADMIN_OPERATION_STORAGE_KEY;
const SELECTED_KEY = ADMIN_SELECTED_MEMBERS_STORAGE_KEY;
const initialMessage: AdminMessage = {
  greeting: "こんにちは。",
  introduction: "おすすめの求人をご案内します。",
  note: "内容をご確認ください。",
};

export default function AdminPage() {
  const { allowDemoReset } = useAdminEnvironment();
  const [step, setStep] = useState<Step>("jobs");
  const [jobs, setJobs] = useState<AdminJobSummary[]>([]);
  const [job, setJob] = useState<AdminJobDetail | null>(null);
  const [candidates, setCandidates] = useState<AdminCandidate[]>([]);
  const [candidateFilter, setCandidateFilter] = useState<CandidateFilterId>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [notificationType, setNotificationType] = useState<NotificationType>("new_job_match");
  const [message, setMessage] = useState<AdminMessage>(initialMessage);
  const [operation, setOperation] = useState<AdminOperation | null>(null);
  const [validation, setValidation] = useState<AdminValidation | null>(null);
  const [deliveries, setDeliveries] = useState<AdminDeliveries | null>(null);
  const [deliveriesOperationId, setDeliveriesOperationId] = useState<string | null>(null);
  const [sessionHistory, setSessionHistory] = useState<SessionHistoryEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [jobsError, setJobsError] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [detailError, setDetailError] = useState(false);
  const [candidatesError, setCandidatesError] = useState(false);
  const [targetsPending, setTargetsPending] = useState(false);
  const [deliveriesLoading, setDeliveriesLoading] = useState(false);
  const [deliveriesError, setDeliveriesError] = useState("");
  const [queueFailure, setQueueFailure] = useState(false);
  const [lineSendMode, setLineSendMode] = useState<AdminLineSendMode | null>(null);
  const [notificationLink, setNotificationLink] = useState<string | null>(null);
  const [validationSnapshot, setValidationSnapshot] = useState<ValidationSnapshot | null>(null);
  const [validationInvalidation, setValidationInvalidation] = useState<string | null>(null);
  const [workflowAction, setWorkflowAction] = useState<WorkflowAction>("idle");
  const [selectedTemplate, setSelectedTemplate] = useState<SelectedTemplateId>("standard");
  const [templateGeneratedMessage, setTemplateGeneratedMessage] = useState<AdminMessage | null>(null);
  const [pendingTemplate, setPendingTemplate] = useState<SelectedTemplateId | null>(null);
  const [pendingJobId, setPendingJobId] = useState<string | null>(null);
  const [resetConfirmationOpen, setResetConfirmationOpen] = useState(false);
  const [centerDisplayName, setCenterDisplayName] = useState(DEFAULT_CENTER_DISPLAY_NAME);
  const [centerDisplayNameDraft, setCenterDisplayNameDraft] = useState(DEFAULT_CENTER_DISPLAY_NAME);
  const [noticeDraft, setNoticeDraft] = useState(initialMessage.note);
  const [appliedNotice, setAppliedNotice] = useState(initialMessage.note);
  const jobRequestSequence = useRef(0);
  const linkRequestSequence = useRef(0);
  const notificationLinkRef = useRef<string | null>(null);
  const workflowLock = useRef(false);
  const historySequence = useRef(0);

  const validationInput = useMemo<ValidationInput>(() => ({
    jobId: selectedJobId,
    selectedMemberIds: [...selected],
    message,
    notificationLink: lineSendMode?.mode === "staging_live" ? notificationLink : job?.job_url ?? null,
    operationId: operation?.operation_id ?? null,
    centerDisplayName,
  }), [centerDisplayName, job, lineSendMode, message, notificationLink, operation, selected, selectedJobId]);
  const validationInputRef = useRef(validationInput);
  validationInputRef.current = validationInput;
  const validationCurrent = isValidationSnapshotCurrent(validationSnapshot, validationInput);
  const currentDeliveries = operation && deliveriesOperationId === operation.operation_id ? deliveries : null;
  const hasTerminalDelivery = Boolean(currentDeliveries?.items.some((item) => item.status === "sent" || item.status === "failed" || item.status === "unknown" || item.status === "skipped"));
  const workflowState = deriveNotificationUiState({
    hasJob: Boolean(job), selectedCount: selected.size,
    messageValid: Object.values(message).every((value) => value.trim()),
    operation, validation, validationCurrent,
    validationWasInvalidated: validationInvalidation !== null,
    busy, action: workflowAction,
    liveBlocked: lineSendMode?.mode === "staging_live" && (lineSendMode.ready !== true || !notificationLink),
    liveLinkReady: lineSendMode?.mode !== "staging_live" || Boolean(notificationLink),
    hasTerminalDelivery, queueFailure,
  });
  notificationLinkRef.current = notificationLink;

  const showError = (value: unknown) => setError(adminErrorMessage(value));
  const clearFeedback = () => { setError(""); setSuccess(""); };

  const loadJobs = useCallback(async (signal?: AbortSignal) => {
    setLoading(true); setJobsError(false); clearFeedback();
    try { setJobs(await adminApi.jobs(signal)); }
    catch (e) { if (!(e instanceof DOMException && e.name === "AbortError")) { setJobsError(true); showError(e); } }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    void loadJobs(controller.signal);
    void adminApi.lineSendMode(controller.signal).then((mode) => {
      if (active) setLineSendMode(mode);
    }).catch((e) => {
      if (active && !(e instanceof DOMException && e.name === "AbortError")) showError(e);
    });
    const saved = sessionStorage.getItem(STORAGE_KEY);
    const savedSelected = sessionStorage.getItem(SELECTED_KEY);
    if (savedSelected) {
      try { setSelected(new Set(JSON.parse(savedSelected) as string[])); } catch { sessionStorage.removeItem(SELECTED_KEY); }
    }
    if (saved) {
      void restoreAdminOperation({
        operationId: saved,
        getOperation: (id) => adminApi.operation(id, controller.signal),
        onOperationRestored: (op, restoredStep) => {
          if (!active) return;
          const restoredNotice = notificationNotice(op.message);
          setOperation(op); setMessage(op.message); setNotificationType(op.notification_type);
          setNoticeDraft(restoredNotice); setAppliedNotice(restoredNotice);
          setSelectedJobId(op.job_id); setStep(restoredStep);
          setSelectedTemplate("custom"); setTemplateGeneratedMessage(null);
          setValidation(null); setValidationSnapshot(null);
          setValidationInvalidation(op.status === "ready" ? "再読み込み後は安全のため再検証が必要です。" : null);
        },
        getJob: (id) => adminApi.job(id, controller.signal),
        getCandidates: (id) => adminApi.candidates(id, controller.signal),
        deliveryActions: {
          sendOperation: adminApi.send,
          getDeliveries: (id) => adminApi.deliveries(id, controller.signal),
        },
        isNotFound: (e) => e instanceof AdminApiError && e.status === 404,
        removeStoredOperationId: () => sessionStorage.removeItem(STORAGE_KEY),
      }).then((result) => {
        if (!active) return;
        if (!result.operation) {
          if (!(result.operationError instanceof DOMException && result.operationError.name === "AbortError")) showError(result.operationError);
          return;
        }
        setJob(result.job); setCandidates(result.candidates);
        setDetailError(result.jobError !== null); setCandidatesError(result.candidatesError !== null);
        if (result.jobError) showError(result.jobError);
        else if (result.candidatesError) showError(result.candidatesError);
        setDeliveries(result.deliveries); setDeliveriesOperationId(result.deliveries ? result.operation.operation_id : null);
        if (result.deliveryError) setDeliveriesError("配信結果を取得できませんでした。配信結果だけを再読み込みしてください。");
      });
    }
    return () => { active = false; controller.abort(); };
  }, [loadJobs]);

  useEffect(() => {
    if (lineSendMode?.mode !== "staging_live" || !lineSendMode.ready || !selectedJobId) {
      linkRequestSequence.current += 1;
      notificationLinkRef.current = null;
      setNotificationLink(null);
      return;
    }
    const controller = new AbortController();
    const requestId = ++linkRequestSequence.current;
    void adminApi.notificationLink(selectedJobId, controller.signal)
      .then((result) => {
        if (requestId !== linkRequestSequence.current) return;
        const previous = notificationLinkRef.current;
        notificationLinkRef.current = result.url;
        setNotificationLink(result.url);
        if (previous !== null && previous !== result.url) {
          setValidationSnapshot(null);
          setValidationInvalidation("求人リンクが更新されたため、再検証が必要です。");
        }
      })
      .catch((error) => {
        if (requestId === linkRequestSequence.current && !(error instanceof DOMException && error.name === "AbortError")) {
          notificationLinkRef.current = null;
          setNotificationLink(null);
        }
      });
    return () => { linkRequestSequence.current += 1; controller.abort(); };
  }, [lineSendMode, selectedJobId]);

  const returnToJobs = useCallback(() => {
    if (busy || workflowAction === "sending") return;
    setStep("jobs");
  }, [busy, workflowAction]);

  function resetCurrentNotificationContext() {
    const cleared = clearedTransientAdminState();
    jobRequestSequence.current += 1; linkRequestSequence.current += 1;
    workflowLock.current = false; setBusy(false); setWorkflowAction("idle");
    setJob(null); setCandidates([]); setSelected(new Set());
    setSelectedJobId(cleared.selectedJobId); setTargetsPending(cleared.targetsPending);
    setValidation(cleared.validation); setDeliveries(cleared.deliveries);
    setDetailError(cleared.detailError); setCandidatesError(cleared.candidatesError);
    setDeliveriesError(cleared.deliveriesError); setQueueFailure(cleared.queueFailure); clearFeedback();
    setValidationSnapshot(null); setValidationInvalidation(null); setOperation(null);
    setSelectedTemplate("standard"); setTemplateGeneratedMessage(null);
    setMessage(initialMessage); setNoticeDraft(initialMessage.note); setAppliedNotice(initialMessage.note);
    setDeliveriesOperationId(null); setSessionHistory([]);
    notificationLinkRef.current = null; setNotificationLink(null);
    sessionStorage.removeItem(STORAGE_KEY); sessionStorage.removeItem(SELECTED_KEY);
  }

  useEffect(() => {
    const handler = () => returnToJobs();
    window.addEventListener(ADMIN_HOME_EVENT, handler);
    return () => window.removeEventListener(ADMIN_HOME_EVENT, handler);
  }, [returnToJobs]);

  function requestJobSelection(jobId: string) {
    if (jobId === selectedJobId || busy || workflowAction === "sending") return;
    const hasCurrentWork = selectedJobId !== null && (operation !== null || candidates.length > 0 || selected.size > 0 || validation !== null || deliveries !== null || !messagesEqual(message, initialMessage));
    if (hasCurrentWork) { setPendingJobId(jobId); return; }
    void switchToJob(jobId);
  }

  async function switchToJob(jobId: string) {
    setPendingJobId(null);
    resetCurrentNotificationContext();
    setSelectedJobId(jobId); setJob(null); setCandidates([]); setSelected(new Set()); setNotificationLink(null); setStep("detail");
    const nextJob = await loadJobAndCandidates(jobId);
    if (nextJob) {
      const generated = createTemplateMessage("standard", centerDisplayName, templateJob(nextJob), initialMessage.note);
      setSelectedTemplate("standard"); setTemplateGeneratedMessage(generated); setMessage(generated);
      setNoticeDraft(initialMessage.note); setAppliedNotice(initialMessage.note);
    }
  }

  async function loadJobAndCandidates(jobId: string): Promise<AdminJobDetail | null> {
    const requestId = ++jobRequestSequence.current;
    setBusy(true); clearFeedback(); setDetailError(false); setCandidatesError(false);
    const [detailResult, candidateResult] = await Promise.allSettled([adminApi.job(jobId), adminApi.candidates(jobId)]);
    if (requestId !== jobRequestSequence.current) return null;
    if (detailResult.status === "fulfilled") setJob(detailResult.value);
    else { setDetailError(true); showError(detailResult.reason); }
    if (candidateResult.status === "fulfilled") setCandidates(candidateResult.value);
    else { setCandidatesError(true); showError(candidateResult.reason); }
    setBusy(false);
    return detailResult.status === "fulfilled" ? detailResult.value : null;
  }

  async function retryDetail() {
    if (!selectedJobId || busy) return; const requestId = jobRequestSequence.current; setBusy(true); clearFeedback();
    try { const result = await adminApi.job(selectedJobId); if (requestId !== jobRequestSequence.current) return; setJob(result); setDetailError(false); }
    catch (e) { if (requestId === jobRequestSequence.current) { setDetailError(true); showError(e); } }
    finally { if (requestId === jobRequestSequence.current) setBusy(false); }
  }

  async function retryCandidates() {
    if (!selectedJobId || busy) return; const requestId = jobRequestSequence.current; setBusy(true); clearFeedback();
    try { const result = await adminApi.candidates(selectedJobId); if (requestId !== jobRequestSequence.current) return; setCandidates(result); setCandidatesError(false); }
    catch (e) { if (requestId === jobRequestSequence.current) { setCandidatesError(true); showError(e); } }
    finally { if (requestId === jobRequestSequence.current) setBusy(false); }
  }

  function toggle(memberId: string) {
    const next = selected.has(memberId) ? new Set<string>() : new Set([memberId]);
    if (memberSelectionsEqual(selected, next)) return;
    setSelected(next); setValidationSnapshot(null); setDeliveries(null); setDeliveriesError(""); setQueueFailure(false);
    if (validation || validationSnapshot || operation?.status === "ready") setValidationInvalidation("対象会員が変更されたため、再検証が必要です。");
  }

  function changeNotificationType(next: NotificationType) {
    if (next === notificationType) return;
    setNotificationType(next); setValidationSnapshot(null); setDeliveries(null); setDeliveriesError("");
    if (validation || validationSnapshot || operation?.status === "ready") setValidationInvalidation("通知種別が変更されたため、再検証が必要です。");
  }

  function changeMessage(next: AdminMessage) {
    if (messagesEqual(message, next)) return;
    if (templateGeneratedMessage && !messagesEqual(templateGeneratedMessage, next)) {
      setSelectedTemplate("custom"); setTemplateGeneratedMessage(null);
    }
    setMessage(next); setValidationSnapshot(null); setDeliveries(null); setDeliveriesError(""); setQueueFailure(false);
    if (validation || validationSnapshot || operation?.status === "ready") setValidationInvalidation("通知本文が変更されたため、再検証が必要です。");
  }

  function templateJob(currentJob: AdminJobDetail): NotificationTemplateJob {
    const summary = jobs.find((item) => item.job_id === currentJob.job_id);
    return {
      title: currentJob.title,
      description: currentJob.description,
      workTime: summary?.work_time,
      workDays: summary?.work_days,
      summary: summary?.summary,
    };
  }

  function applyTemplate(next: SelectedTemplateId) {
    if (next === "custom" || !job) return;
    const template = notificationTemplates.find((item) => item.id === next);
    if (!template) return;
    if (template.requiresJob && !job.title.trim()) { setError("先に求人を選択してください。"); return; }
    const currentIsTemplateInitial = templateGeneratedMessage !== null && messagesEqual(message, templateGeneratedMessage);
    const requiresConfirmation = !currentIsTemplateInitial && (operation !== null || Object.values(message).some((value) => value.trim()));
    if (requiresConfirmation) { setPendingTemplate(next); return; }
    commitTemplate(next);
  }

  function commitTemplate(next: SelectedTemplateId) {
    if (next === "custom" || !job) return;
    const generated = createTemplateMessage(next, centerDisplayName, templateJob(job), noticeDraft);
    setPendingTemplate(null);
    setSelectedTemplate(next); setTemplateGeneratedMessage(generated); clearFeedback();
    setAppliedNotice(noticeDraft);
    if (messagesEqual(message, generated)) { setSuccess("選択したテンプレートが適用されています。"); return; }
    changeMessageFromTool(generated, "テンプレートが適用されたため、再検証が必要です。");
    setSuccess("通知テンプレートを適用しました。内容を確認して保存してください。");
  }

  function applyEditorFields() {
    const nextName = centerDisplayNameDraft.trim().slice(0, CENTER_DISPLAY_NAME_MAX_LENGTH);
    const nextNotice = noticeDraft.trim();
    if (!nextName) { setCenterDisplayNameDraft(centerDisplayName); return; }
    let nextMessage = message;
    const templateIsUnedited = selectedTemplate !== "custom" && templateGeneratedMessage !== null && messagesEqual(message, templateGeneratedMessage);
    if (templateIsUnedited && job) {
      nextMessage = createTemplateMessage(selectedTemplate, nextName, templateJob(job), nextNotice);
    } else {
      nextMessage = replaceExactCenterName(nextMessage, centerDisplayName, nextName);
      nextMessage = replaceExactNotice(nextMessage, appliedNotice, nextNotice);
    }
    setCenterDisplayName(nextName); setCenterDisplayNameDraft(nextName);
    setNoticeDraft(nextNotice); setAppliedNotice(nextNotice);
    if (!messagesEqual(message, nextMessage)) {
      if (templateIsUnedited) setTemplateGeneratedMessage(nextMessage);
      else { setSelectedTemplate("custom"); setTemplateGeneratedMessage(null); }
      changeMessageFromTool(nextMessage, "センター名または注意事項が本文へ反映されたため、再検証が必要です。");
    }
    setSuccess(messagesEqual(message, nextMessage) ? "本文は最新の内容です。" : "センター名と注意事項を通知本文へ反映しました。");
  }

  function changeMessageFromTool(next: AdminMessage, reason: string) {
    setMessage(next); setValidationSnapshot(null); setDeliveries(null); setDeliveriesError(""); setQueueFailure(false);
    if (validation || validationSnapshot || operation?.status === "ready") setValidationInvalidation(reason);
  }

  async function beginOperation() {
    if (!job || selected.size === 0 || busy) return;
    setBusy(true); clearFeedback();
    try {
      const current = await createOrSaveTargets({
        operation, jobId: job.job_id,
        createBody: { job_id: job.job_id, notification_type: notificationType, ...message },
        selectedMemberIds: [...selected], create: adminApi.createOperation,
        saveTargets: adminApi.updateTargets, reload: adminApi.operation,
        onCreated: (created) => {
          setOperation(created); setTargetsPending(true);
          sessionStorage.setItem(STORAGE_KEY, created.operation_id);
          sessionStorage.setItem(SELECTED_KEY, JSON.stringify([...selected]));
        },
      });
      setOperation(current); setTargetsPending(false); setValidation(null);
      sessionStorage.setItem(SELECTED_KEY, JSON.stringify([...selected]));
      setSuccess("対象者を保存しました。"); setStep("edit");
    } catch (e) {
      showError(e);
      if (operation || sessionStorage.getItem(STORAGE_KEY)) {
        setTargetsPending(true);
        setSuccess("通知操作は作成済みです。対象者の保存を再試行してください。");
      }
    }
    finally { setBusy(false); }
  }

  async function saveMessage() {
    if (!operation || !workflowState.canSaveDraft || workflowLock.current) return;
    workflowLock.current = true; setWorkflowAction("saving"); setBusy(true); clearFeedback();
    try { const current = await adminApi.updateOperation(operation.operation_id, message); setOperation(current); setValidation(null); recordSessionEvent(current.operation_id, "下書き保存", "保存済み", "現在の通知本文を保存しました。"); setSuccess("通知文を保存しました。"); }
    catch (e) { showError(e); }
    finally { workflowLock.current = false; setWorkflowAction("idle"); setBusy(false); }
  }

  async function validate() {
    if (!operation || !workflowState.canValidate || workflowLock.current) return;
    const startedSnapshot = createValidationSnapshot(validationInputRef.current);
    workflowLock.current = true; setWorkflowAction("validating"); setBusy(true); clearFeedback();
    setValidation(null); setValidationSnapshot(null); setValidationInvalidation(null);
    try {
      const result = await saveThenValidate({ operationId: operation.operation_id, message, save: adminApi.updateOperation, validate: adminApi.validate });
      const currentOperation = await adminApi.operation(operation.operation_id);
      setOperation(currentOperation); setValidation(result.validation);
      if (isValidationSnapshotCurrent(startedSnapshot, validationInputRef.current)) {
        setMessage(result.operation.message); setValidationSnapshot(startedSnapshot); setValidationInvalidation(null); setStep("confirm");
      } else {
        setValidationSnapshot(null); setValidationInvalidation("検証中に内容が変更されたため、再検証が必要です。");
        recordSessionEvent(operation.operation_id, "事前検証", "検証失効", "検証中に内容が変更されたため、結果を送信許可として使用しません。");
      }
    }
    catch (e) { setValidation(null); setValidationSnapshot(null); setValidationInvalidation(null); recordSessionEvent(operation.operation_id, "事前検証", "完了せず", "事前検証を完了できませんでした。"); showError(e); setOperation(await adminApi.operation(operation.operation_id).catch(() => operation)); }
    finally { workflowLock.current = false; setWorkflowAction("idle"); setBusy(false); }
  }

  async function fakeSend() {
    if (!operation || !workflowState.canSend || workflowLock.current) return;
    workflowLock.current = true; setWorkflowAction("sending"); setBusy(true); clearFeedback();
    setQueueFailure(false); setDeliveriesError("");
    try {
      const result = await sendThenLoadDeliveries({
        operationId: operation.operation_id, send: adminApi.send, loadDeliveries: adminApi.deliveries,
        onSent: (sent) => { setOperation(sent); setStep("result"); setDeliveriesLoading(true); },
      });
      if (validationInputRef.current.operationId === operation.operation_id) { setDeliveries(result.deliveries); setDeliveriesOperationId(result.deliveries ? operation.operation_id : null); }
      if (result.deliveryError) setDeliveriesError("配信結果を取得できませんでした。配信結果だけを再読み込みしてください。");
    } catch (e) {
      if (e instanceof AdminApiError && e.status === 503 && e.code === "service_unavailable") {
        setQueueFailure(true); setError("送信処理は開始されませんでした。現在の状態を確認してください。自動再送は行いません。");
      } else showError(e);
      setValidationSnapshot(null); setValidationInvalidation("送信処理後の状態を再確認し、必要に応じて再検証してください。");
      setOperation(await adminApi.operation(operation.operation_id).catch(() => operation));
    }
    finally { workflowLock.current = false; setWorkflowAction("idle"); setDeliveriesLoading(false); setBusy(false); }
  }

  async function loadDeliveriesOnly() {
    if (!operation || deliveriesLoading) return;
    const operationId = operation.operation_id;
    setDeliveriesLoading(true); setDeliveriesError("");
    try {
    const result = await reloadDeliveryResults({ operation, actions: { sendOperation: adminApi.send, getDeliveries: adminApi.deliveries } });
    if (validationInputRef.current.operationId !== operationId) return;
    setOperation(result.operation); setDeliveries(result.deliveries); setDeliveriesOperationId(result.deliveries ? operationId : null);
    if (result.deliveryError) setDeliveriesError("配信結果を取得できませんでした。しばらくして再読み込みしてください。");
    } finally { setDeliveriesLoading(false); }
  }

  async function reset() {
    if (busy) return;
    setResetConfirmationOpen(false);
    setBusy(true); clearFeedback();
    try {
      await adminApi.reset(); sessionStorage.removeItem(STORAGE_KEY); sessionStorage.removeItem(SELECTED_KEY);
      setOperation(null); setValidation(null); setDeliveries(null); setJob(null); setCandidates([]); setSelected(new Set()); setMessage(initialMessage); setTargetsPending(false); setDeliveriesError(""); setQueueFailure(false); setStep("jobs");
      setSelectedTemplate("standard"); setTemplateGeneratedMessage(null); setCenterDisplayName(DEFAULT_CENTER_DISPLAY_NAME); setCenterDisplayNameDraft(DEFAULT_CENTER_DISPLAY_NAME);
      setDeliveriesOperationId(null); setSessionHistory([]);
      workflowLock.current = false; setValidationSnapshot(null); setValidationInvalidation(null); setWorkflowAction("idle"); notificationLinkRef.current = null; setNotificationLink(null);
      await loadJobs(); setSuccess("デモデータをリセットしました。");
    } catch (e) { showError(e); }
    finally { setBusy(false); }
  }

  function recordSessionEvent(operationId: string, name: string, status: string, description: string) {
    const event: SessionHistoryEvent = { id: `session-${++historySequence.current}`, operationId, jobName: job?.title ?? "求人名を取得できません", name, status, occurredAt: new Date().toISOString(), description };
    setSessionHistory((current) => [event, ...current].slice(0, 10));
  }

  return <AdminShell mode={lineSendMode}><main className="admin-main">
    {allowDemoReset && <div className="admin-toolbar-actions"><button className="admin-button danger" onClick={() => setResetConfirmationOpen(true)} disabled={busy}>デモデータをリセット</button></div>}
    <div className="sr-status" aria-live="polite">{loading || busy ? "処理中です…" : ""}</div>
    {error && <div className="admin-error" role="alert">{error}</div>}
    {success && <div className="admin-success" role="status">{success}</div>}

    <div className="admin-panel-grid">
    <div className="admin-upper-workspace">
    <div className="admin-left-stack">
    <AdminPanel number={1} title="求人選択" badge={`${jobs.length}件`} actions={step !== "jobs" ? <button className="admin-button secondary compact" disabled={busy} onClick={returnToJobs}>求人を選び直す</button> : undefined}>
      <JobSelectionPanel jobs={jobs} selectedJobId={selectedJobId} selectedJob={job} loading={loading} error={jobsError} busy={busy || workflowAction === "sending"} retry={() => void loadJobs()} select={async (jobId) => requestJobSelection(jobId)} />
    </AdminPanel>
    <AdminPanel number={2} title="対象候補会員" badge={job ? `${job.title}・${candidates.length}人` : undefined} actions={job ? <CandidateFilterMenu value={candidateFilter} onChange={setCandidateFilter} /> : undefined}>
      {!selectedJobId ? <p className="admin-panel-empty">求人を選択すると、通知候補会員を読み込みます。</p> : !job ? <div className={detailError ? "admin-error" : "admin-info"} role={detailError ? "alert" : "status"}>{detailError ? <><p>選択求人の詳細を取得できませんでした。</p><button className="admin-button secondary" disabled={busy} onClick={() => void retryDetail()}>求人詳細を再読み込み</button></> : "選択求人を読み込んでいます。"}</div> : <CandidateSelectionPanel job={job} candidates={candidates} selected={selected} notificationType={notificationType} setNotificationType={changeNotificationType} toggle={toggle} begin={beginOperation} busy={busy} error={candidatesError} retry={retryCandidates} targetsPending={targetsPending} singleRecipient={lineSendMode?.mode === "staging_live"} editable={step === "detail" && !workflowState.terminal} filter={candidateFilter} setFilter={setCandidateFilter} />}
    </AdminPanel>
    </div>
    <AdminPanel number={3} title="通知文編集" badge={job?.title} status={workflowState.state === "stale" ? "再検証が必要" : step === "edit" ? "現在の操作" : operation ? "下書きあり" : "未準備"}>
      {!job || !operation ? <p className="admin-panel-empty">対象候補会員を保存すると、通知文を編集できます。</p> : step === "edit" && !workflowState.terminal ? <MessageEditorPanel job={job} message={message} setMessage={changeMessage} selectedTemplate={selectedTemplate} applyTemplate={applyTemplate} centerDisplayNameDraft={centerDisplayNameDraft} setCenterDisplayNameDraft={setCenterDisplayNameDraft} noticeDraft={noticeDraft} setNoticeDraft={setNoticeDraft} applyEditorFields={applyEditorFields} editorFieldsChanged={centerDisplayNameDraft.trim() !== centerDisplayName || noticeDraft.trim() !== appliedNotice} busy={busy} validationStale={workflowState.state === "stale"} lineSendMode={lineSendMode} notificationLink={notificationLink} /> : <MessageReadOnlySummary message={operation.message} edit={step === "confirm" && validation !== null && validationCurrent && !workflowState.terminal && workflowAction !== "sending" ? () => setStep("edit") : undefined} />}
    </AdminPanel>
    <AdminPanel number={4} title="送信前確認">
      {step === "confirm" && operation && validation ? <SendConfirmationPanel operation={operation} validation={queueFailure ? { ...validation, can_proceed: false } : validation} candidates={candidates} selected={selected} save={saveMessage} send={fakeSend} revalidate={validate} busy={busy} canSaveDraft={workflowState.canSaveDraft} canValidate={workflowState.canValidate} canSend={workflowState.canSend} validationCurrent={validationCurrent} action={workflowAction} targets={() => setStep("detail")} lineSendMode={lineSendMode} queueFailure={queueFailure} /> : step === "result" && operation ? <div className="completion-notice" role="status"><strong>送信処理は完了しています。</strong><p>{operation.status === "completed_with_errors" ? "一部の配信で失敗または結果不明があります。配信状況サマリーを確認してください。" : "配信状況サマリーで結果を確認してください。"}</p><p>結果不明の通知は自動再送されません。</p></div> : <SendPreparationState operation={operation} validation={validation} candidates={candidates} selected={selected} save={saveMessage} validate={validate} canSaveDraft={workflowState.canSaveDraft} canValidate={workflowState.canValidate} busy={busy} action={workflowAction} validationCurrent={validationCurrent} lineSendMode={lineSendMode} />}
    </AdminPanel>
    </div>
    <div className="admin-lower-workspace">
    <AdminPanel number={5} title="配信状況サマリー" status={step === "result" ? "結果表示" : "未送信"}>
      <DeliverySummaryPanel operation={operation} deliveries={currentDeliveries} loading={deliveriesLoading} error={deliveriesError} retry={loadDeliveriesOnly} />
    </AdminPanel>
    <AdminPanel number={6} title="最近の操作履歴" status={operation ? "現在のoperation" : "未作成"}>
      <RecentOperationHistory operation={operation} jobName={job?.title ?? null} deliveries={currentDeliveries} sessionEvents={sessionHistory} />
    </AdminPanel>
    </div>
    </div>
    {pendingTemplate && <Modal title="通知テンプレートを変更しますか？" onClose={() => setPendingTemplate(null)} footer={<><button className="admin-button secondary" type="button" data-modal-initial-focus onClick={() => setPendingTemplate(null)}>キャンセル</button><button className="admin-button" type="button" onClick={() => commitTemplate(pendingTemplate)}>テンプレートを適用</button></>}><p>現在の通知本文は、選択したテンプレートの内容で置き換えられます。</p></Modal>}
    {pendingJobId && <Modal title="求人を変更しますか？" onClose={() => setPendingJobId(null)} footer={<><button className="admin-button secondary" type="button" data-modal-initial-focus onClick={() => setPendingJobId(null)}>キャンセル</button><button className="admin-button danger" type="button" onClick={() => void switchToJob(pendingJobId)}>求人を変更する</button></>}><p>求人を変更すると、現在の通知本文、対象会員、検証結果は破棄されます。保存済みの旧通知履歴は削除されません。</p></Modal>}
    {resetConfirmationOpen && <Modal title="デモデータをリセットしますか？" onClose={() => setResetConfirmationOpen(false)} footer={<><button className="admin-button secondary" type="button" data-modal-initial-focus onClick={() => setResetConfirmationOpen(false)}>キャンセル</button><button className="admin-button danger" type="button" onClick={() => void reset()}>リセットする</button></>}><p>通知operation、対象者、送信結果、監査履歴を消去します。fixture求人は残ります。</p></Modal>}
  </main></AdminShell>;
}

function Jobs({ jobs, loading, busy, retry, select }: { jobs: AdminJobSummary[]; loading: boolean; busy: boolean; retry: () => void; select: (id: string) => Promise<void> }) {
  if (loading) return <div className="admin-info">求人を読み込んでいます。</div>;
  if (!jobs.length) return <div className="admin-card"><h3>表示できる求人がありません</h3><p className="admin-muted">デモデータを再読み込みしてください。</p><button className="admin-button" onClick={retry}>再読み込み</button></div>;
  return <><div className="admin-actions"><button className="admin-button secondary" onClick={retry}>再読み込み</button></div><section className="admin-grid admin-section">{jobs.map((job) => <article className="admin-card" key={job.job_id}><span className="admin-status">{jobStatus(job.status)}</span><h3>{job.title}</h3><p>{job.location ?? "勤務地未設定"}・募集 {job.openings}名</p><p className="admin-muted">version {job.version}</p><p>{job.summary ?? "概要はありません。"}</p><button className="admin-button" disabled={busy} onClick={() => void select(job.job_id)}>詳細を見る</button></article>)}</section></>;
}

function JobAndCandidates({ job, candidates, selected, selectable, notificationType, setNotificationType, toggle, setSelected, begin, busy, back, detailError, candidatesError, retryDetail, retryCandidates, targetsPending }: { job: AdminJobDetail | null; candidates: AdminCandidate[]; selected: Set<string>; selectable: AdminCandidate[]; notificationType: NotificationType; setNotificationType: (v: NotificationType) => void; toggle: (id: string) => void; setSelected: (v: Set<string>) => void; begin: () => Promise<void>; busy: boolean; back: () => void; detailError: boolean; candidatesError: boolean; retryDetail: () => Promise<void>; retryCandidates: () => Promise<void>; targetsPending: boolean }) {
  return <>{detailError && <div className="admin-error">求人詳細を取得できませんでした。<button className="admin-button secondary" disabled={busy} onClick={() => void retryDetail()}>求人詳細を再読み込み</button></div>}{job && <article className="admin-card"><span className="admin-status">{jobStatus(job.status)}</span><h2>{job.title}</h2>{job.status !== "published" && <div className="admin-error">この求人は募集中ではありません。</div>}<p>{job.description}</p><p><strong>勤務地：</strong>{job.location ?? "未設定"}</p><p><strong>条件：</strong>{job.conditions.join("、") || "未設定"}</p><p><strong>募集：</strong>{job.openings}名　<strong>version：</strong>{job.version}</p><p><a className="admin-link" href={job.job_url} target="_blank" rel="noreferrer">求人リンクを確認</a></p>{job.contact && <p><strong>問い合わせ：</strong>{job.contact}</p>}</article>}
    <section className="admin-card admin-section"><h2>候補会員</h2><p>選択可能な候補だけを全選択します。LINE未連携者を選択した場合は送信時にskippedになります。</p><div className="admin-actions"><button className="admin-button secondary" onClick={() => setSelected(new Set(selectable.map((x) => x.member_id)))}>選択可能な候補を全選択</button><button className="admin-button secondary" onClick={() => setSelected(new Set())}>全解除</button><strong>{selected.size}名選択中</strong></div>{!candidates.length ? <p className="admin-muted">候補会員はいません。</p> : <div className="admin-grid admin-section">{candidates.map((candidate) => <label className="admin-card candidate" key={candidate.member_id}><input type="checkbox" checked={selected.has(candidate.member_id)} disabled={!candidate.eligible} onChange={() => toggle(candidate.member_id)} /><span><strong>{candidate.display_name}</strong><br/><span className="admin-muted">{candidate.member_id}</span><br/>{candidate.line_linked ? "LINE連携済み" : "LINE未連携（skipped予定）"}・{candidate.eligible ? "対象" : "対象外"}{candidate.reason && <><br/>{reasonLabel(candidate.reason)}</>}</span></label>)}</div>}
      {candidatesError && <div className="admin-error">候補会員を取得できませんでした。<button className="admin-button secondary" disabled={busy} onClick={() => void retryCandidates()}>候補一覧を再読み込み</button></div>}{targetsPending && <div className="admin-info">通知操作は作成済みです。対象者の保存を再試行してください。</div>}<div className="admin-field admin-section"><label htmlFor="notification-type">通知種別</label><select id="notification-type" value={notificationType} onChange={(e) => setNotificationType(e.target.value as NotificationType)}><option value="new_job_match">新着求人マッチ</option><option value="existing_job_match">既存求人マッチ</option><option value="custom_job">個別求人</option></select></div><div className="admin-actions admin-section"><button className="admin-button secondary" onClick={back}>求人一覧へ戻る</button><button className="admin-button" disabled={!job || !selected.size || busy || job.status !== "published"} onClick={() => void begin()}>{busy ? "保存中…" : targetsPending ? "対象者の保存を再試行" : "通知文の編集へ"}</button></div></section></>;
}

function Editor({ job, message, setMessage, save, validate, busy, back, lineSendMode, notificationLink }: { job: AdminJobDetail; message: AdminMessage; setMessage: (v: AdminMessage) => void; save: () => Promise<void>; validate: () => Promise<void>; busy: boolean; back: () => void; lineSendMode: AdminLineSendMode | null; notificationLink: string | null }) {
  const valid = Object.values(message).every((v) => v.trim());
  const live = lineSendMode?.mode === "staging_live";
  const ready = live && lineSendMode?.ready === true;
  return <div className="admin-grid"><section className="admin-card"><h2>通知文を編集</h2><div className="admin-form">{(["greeting","introduction","note"] as const).map((key) => <div className="admin-field" key={key}><label htmlFor={key}>{key === "greeting" ? "挨拶" : key === "introduction" ? "求人紹介文" : "補足"}</label><textarea id={key} value={message[key]} onChange={(e) => setMessage({ ...message, [key]: e.target.value })}/><small>{message[key].length}文字</small></div>)}</div><div className="admin-info"><strong>固定項目</strong><p>センター：デモシルバー人材センター<br/>求人リンク：{ready ? notificationLink ?? "取得できません" : job.job_url}<br/>問い合わせ：{job.contact ?? "未設定"}<br/>安全上の注意：{ready ? "実LINE通知が検証者1名へ送信され、【検証通知】が付きます。" : live ? "実LINE送信設定が未完了のため送信できません。" : "これはFake送信による検証用の処理確認です。実LINE通知は送信されません。"}<br/>求人ID：{job.job_id}</p></div><div className="admin-actions"><button className="admin-button secondary" onClick={back}>対象変更へ戻る</button><button className="admin-button secondary" disabled={!valid || busy} onClick={() => void save()}>保存</button><button className="admin-button" disabled={!valid || busy} onClick={() => void validate()}>{busy ? "保存・validate中…" : "保存してvalidate"}</button></div></section><Preview job={job} message={message} lineSendMode={lineSendMode} notificationLink={notificationLink}/></div>;
}

function Preview({ job, message, lineSendMode, notificationLink }: { job: AdminJobDetail; message: AdminMessage; lineSendMode: AdminLineSendMode | null; notificationLink: string | null }) { const liveReady = lineSendMode?.mode === "staging_live" && lineSendMode.ready === true; return <aside className="preview"><h2>LINE風プレビュー</h2><p className="fake-warning">送信前プレビューです。</p><div className="preview-bubble">{liveReady && <>{lineSendMode.message_prefix}{"\n\n"}</>}{message.greeting}{"\n\n"}{message.introduction}{"\n\n"}{message.note}{"\n\n"}求人：{job.title}{"\n"}求人リンク：{liveReady ? notificationLink ?? "取得できません" : job.job_url}{"\n"}問い合わせ：{job.contact ?? "未設定"}{"\n"}求人ID：{job.job_id}{"\n\n"}※検証用通知です。</div></aside>; }

function Confirmation({ job, operation, validation, candidates, selected, send, revalidate, busy, edit, targets, lineSendMode, notificationLink }: { job: AdminJobDetail; operation: AdminOperation; validation: AdminValidation; candidates: AdminCandidate[]; selected: Set<string>; send: () => Promise<void>; revalidate: () => Promise<void>; busy: boolean; edit: () => void; targets: () => void; lineSendMode: AdminLineSendMode | null; notificationLink: string | null }) {
  const live = lineSendMode?.mode === "staging_live";
  const ready = live && lineSendMode?.ready === true;
  const oneRecipient = validation.selected_count === 1 && validation.sendable_count === 1;
  return <><p className="fake-warning">{ready ? "実LINE通知が検証者1名へ送信されます。送信後は取り消せません。対象・求人・本文・完全なLIFFリンクを確認してください。" : live ? "実LINE送信は設定不備によりブロックされています。" : "これはFake送信による検証用の処理確認です。実LINE通知は送信されません。"}</p><section className="admin-card"><h2>送信前確認</h2><p><strong>{job.title}</strong>（version {job.version}）</p><p>通知種別：{notificationTypeLabel(operation.notification_type)}</p><p>求人リンク：{ready ? notificationLink ?? "取得できません" : job.job_url}</p><div className="summary-grid"><Summary label="選択" value={validation.selected_count}/><Summary label="送信可能" value={validation.sendable_count}/><Summary label="skipped予定" value={validation.skipped_count}/></div>{live && !oneRecipient && <div className="admin-error">実LINE検証送信は送信可能な1名だけを選択してください。</div>}{live && !ready && <div className="admin-error">実LINE送信設定を確認してください。</div>}{validation.version_changed && <div className="admin-error">求人versionが変更されています。</div>}{!validation.can_proceed && <div className="admin-error">この状態では送信できません。{validation.reasons.map(reasonLabel).join("、")}</div>}<h3>対象者</h3><ul>{candidates.filter((x) => selected.has(x.member_id)).map((x) => <li key={x.member_id}>{x.display_name} — {x.line_linked ? "送信対象" : "LINE未連携・skipped予定"}</li>)}</ul><h3>完成した通知文</h3><div className="preview-bubble">{ready && lineSendMode?.message_prefix}{ready && lineSendMode?.message_prefix && "\n\n"}{operation.message.greeting}{"\n\n"}{operation.message.introduction}{"\n\n"}{operation.message.note}</div><p className="admin-muted">送信時にもBackendで再validateされます。この結果だけを永続的な送信許可として扱いません。</p><div className="admin-actions"><button className="admin-button secondary" onClick={edit}>文面編集へ戻る</button><button className="admin-button secondary" onClick={targets}>対象変更へ戻る</button><button className="admin-button secondary" disabled={busy} onClick={() => void revalidate()}>再validate</button><button className="admin-button" disabled={busy || !validation.can_proceed || operation.status !== "ready" || (live && (!ready || !oneRecipient || !notificationLink))} onClick={() => void send()}>{busy ? "送信中…" : ready ? "実LINE検証送信を実行" : live ? "実LINE送信は利用できません" : "Fake送信を実行"}</button></div></section></>;
}

function Result({ operation, deliveries, deliveriesLoading, deliveriesError, retry, lineSendMode }: { operation: AdminOperation; deliveries: AdminDeliveries | null; deliveriesLoading: boolean; deliveriesError: string; retry: () => Promise<void>; lineSendMode: AdminLineSendMode | null }) {
  const title = lineSendMode?.mode === "staging_live" && lineSendMode.ready ? "実LINE送信結果" : "Fake送信結果";
  return <><section className="admin-card"><h2>{title}</h2><span className="admin-status">{statusLabel(operation.status)}</span><p>完了時刻：{formatTime(operation.completed_at)}</p>{operation.status === "completed_with_errors" && <div className="admin-error">一部の通知でエラーまたは結果不明がありました。</div>}<p className="admin-muted">再送・retry機能はありません。unknownは自動再送されません。</p></section>{deliveriesLoading && <div className="admin-info">配信結果を読み込んでいます。</div>}{deliveriesError && <div className="admin-error">{deliveriesError}<button className="admin-button secondary" disabled={deliveriesLoading} onClick={() => void retry()}>配信結果を再読み込み</button></div>}{deliveries ? <section className="admin-card admin-section"><h2>配信結果</h2><div className="summary-grid">{(["sent","failed","unknown","skipped","pending"] as const).map((status) => <Summary key={status} label={statusLabel(status)} value={deliveries.summary[status]}/>)}</div><p>合計 {deliveries.items.length}件</p><div className="delivery-list">{deliveries.items.map((item) => <div className="delivery" key={item.delivery_id}><div><strong>{item.member_id}</strong><br/><span className="admin-muted">{item.status === "unknown" ? "結果不明・自動再送なし" : reasonLabel(item.reason_code)}</span></div><div><span className="admin-status">{statusLabel(item.status)}</span><br/><small>{formatTime(item.sent_at ?? item.updated_at)}</small></div></div>)}</div></section> : !deliveriesError && !deliveriesLoading && <div className="admin-info">配信結果はありません。</div>}</>;
}

function Summary({ label, value }: { label: string; value: number }) { return <div className="summary-item"><strong>{value}</strong><br/><span>{label}</span></div>; }
function stepTitle(step: Step) { return ({ jobs:"求人一覧",detail:"求人詳細・候補選択",edit:"通知文編集",confirm:"validate結果・送信前確認",result:"送信結果" })[step]; }
function jobStatus(value: string) { return ({ published:"募集中",closed:"終了",draft:"下書き",suspended:"停止中" } as Record<string,string>)[value] ?? value; }
function statusLabel(value: string) { return ({ draft:"下書き",validating:"確認中",ready:"送信準備完了",blocked_external_system:"外部情報確認不可",sending:"送信処理中",completed:"完了",completed_with_errors:"一部エラーで完了",cancelled:"取消",sent:"送信済み",failed:"失敗",unknown:"結果不明",skipped:"対象外",pending:"処理待ち" } as Record<string,string>)[value] ?? value; }
function notificationTypeLabel(value: NotificationType) { return ({ new_job_match:"新着求人マッチ",existing_job_match:"既存求人マッチ",custom_job:"個別求人" })[value]; }
function reasonLabel(value: string | null) { if (!value) return "—"; return ({ line_not_linked:"LINE未連携",not_selected:"未選択",member_ineligible:"対象外",job_closed:"求人終了",job_version_changed:"求人version変更",recipient_unavailable:"送信先を利用できません",line_temporary_error:"一時的な送信エラー",line_unknown_result:"送信結果不明" } as Record<string,string>)[value] ?? "対象条件を満たしません"; }
function formatTime(value: string | null) { return value ? new Intl.DateTimeFormat("ja-JP", { dateStyle:"medium", timeStyle:"short" }).format(new Date(value)) : "—"; }

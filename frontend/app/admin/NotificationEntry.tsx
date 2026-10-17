"use client";
import { useEffect, useState, type ReactNode } from "react";
import { SelectionModeDialog } from "./SelectionModeDialog";
import { AutomaticNotification } from "./AutomaticNotification";
import { notificationEntryUrl, parseNotificationEntry, parseResumeOperation, type SelectionMode } from "./automatic-workflow";
import { adminApi, adminErrorMessage } from "../lib/admin-api";
import { LoadingOverlay } from "./LoadingOverlay";

export function NotificationEntry({ manual }: { manual: (jobId: string | null, operationId: string | null) => ReactNode }) {
  const [entry, setEntry] = useState<{ mode: SelectionMode | null; jobId: string | null; operationId: string | null } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    const parsed = parseNotificationEntry(window.location.search);
    const operationId = parseResumeOperation(window.location.search);
    if (new URLSearchParams(window.location.search).has("operationId")) {
      if (!operationId) {
        setError("通知の再開URLが不正です。新しい通知のモードを選択してください。");
        setEntry({ mode: null, jobId: null, operationId: null });
      } else {
        // The saved operation, not a mode query parameter, determines its workflow.
        void adminApi.operation(operationId, controller.signal).then(op => {
          if (!controller.signal.aborted) setEntry({ mode: op.automatic_selection ? "auto" : "manual", jobId: null, operationId });
        }).catch(e => { if (!controller.signal.aborted) {
          setError(adminErrorMessage(e)); setEntry({ mode: null, jobId: null, operationId: null });
        } });
      }
    } else {
      // An ordinary navigation never inherits an earlier operation from sessionStorage.
      setEntry({ ...parsed, operationId: null });
    }
    return () => controller.abort();
  }, []);
  if (!entry) return <LoadingOverlay active status="通知作成の状態を確認中…" />;
  const choose = (mode: SelectionMode) => {
    window.history.replaceState(null, "", notificationEntryUrl(mode, entry.jobId));
    setEntry({ ...entry, mode });
  };
  if (!entry.mode) return <>{error && <p role="alert">{error}</p>}<SelectionModeDialog choose={choose} close={() => choose("manual")} /></>;
  return entry.mode === "manual" ? manual(entry.jobId, entry.operationId) : <AutomaticNotification initialJobId={entry.jobId} resumeOperationId={entry.operationId} />;
}

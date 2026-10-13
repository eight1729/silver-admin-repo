"use client";
import { useEffect, useState, type ReactNode } from "react";
import { SelectionModeDialog } from "./SelectionModeDialog";
import { AutomaticNotification } from "./AutomaticNotification";
import { AUTO_OPERATION_KEY, notificationEntryUrl, parseNotificationEntry, type SelectionMode } from "./automatic-workflow";
import { ADMIN_OPERATION_STORAGE_KEY } from "./admin-session";

export function NotificationEntry({ manual }: { manual: (jobId: string | null) => ReactNode }) {
  const [entry, setEntry] = useState<{ mode: SelectionMode | null; jobId: string | null } | null>(null);
  useEffect(() => {
    const parsed = parseNotificationEntry(window.location.search);
    if (!parsed.mode && !window.location.search) {
      if (sessionStorage.getItem(AUTO_OPERATION_KEY)) parsed.mode = "auto";
      else if (sessionStorage.getItem(ADMIN_OPERATION_STORAGE_KEY)) parsed.mode = "manual";
    }
    setEntry(parsed);
  }, []);
  if (!entry) return <p role="status">通知作成を準備しています。</p>;
  const choose = (mode: SelectionMode) => {
    window.history.replaceState(null, "", notificationEntryUrl(mode, entry.jobId));
    setEntry({ ...entry, mode });
  };
  if (!entry.mode) return <SelectionModeDialog choose={choose} close={() => choose("manual")} />;
  return entry.mode === "manual" ? manual(entry.jobId) : <AutomaticNotification initialJobId={entry.jobId} />;
}

"use client";
import { useEffect, useState } from "react";
import { ADMIN_HOME_EVENT, ADMIN_NEW_EVENT } from "./AdminHomeButton";
import { Modal } from "../components/Modal";

export function JobsNavigationGuard({ busy, dirty }: { busy: boolean; dirty: boolean }) {
  const [destination, setDestination] = useState<string | null>(null);
  useEffect(() => {
    const navigate = (path: string) => {
      if (busy) return;
      if (dirty) setDestination(path);
      else window.location.assign(path);
    };
    const handler = () => navigate("/admin/jobs");
    const newNotification = (event: Event) => { event.preventDefault(); navigate("/admin"); };
    window.addEventListener(ADMIN_HOME_EVENT, handler);
    window.addEventListener(ADMIN_NEW_EVENT, newNotification);
    return () => { window.removeEventListener(ADMIN_HOME_EVENT, handler); window.removeEventListener(ADMIN_NEW_EVENT, newNotification); };
  }, [busy, dirty]);
  const label = destination === "/admin" ? "新しい通知を作成" : "求人一覧へ戻る";
  return destination ? <Modal placement="center" title={destination === "/admin" ? "新しい通知を作成しますか？" : "求人一覧へ戻りますか？"} onClose={() => setDestination(null)} footer={<>
    <button className="admin-button secondary" data-modal-initial-focus onClick={() => setDestination(null)}>編集を続ける</button>
    <button className="admin-button" disabled={busy} onClick={() => { if (!busy) window.location.assign(destination); }}>{label}</button>
  </>}><p>未保存の変更は失われます。保存済みの通知は削除しません。</p></Modal> : null;
}

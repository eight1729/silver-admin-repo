"use client";
import { useEffect, useState } from "react";
import { ADMIN_HOME_EVENT } from "./AdminHomeButton";
import { Modal } from "../components/Modal";

export function JobsNavigationGuard({ busy, dirty }: { busy: boolean; dirty: boolean }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const handler = () => {
      if (busy) return;
      if (dirty) setOpen(true);
      else window.location.assign("/admin/jobs");
    };
    window.addEventListener(ADMIN_HOME_EVENT, handler);
    return () => window.removeEventListener(ADMIN_HOME_EVENT, handler);
  }, [busy, dirty]);
  return open ? <Modal placement="center" title="求人一覧へ戻りますか？" onClose={() => setOpen(false)} footer={<>
    <button className="admin-button secondary" data-modal-initial-focus onClick={() => setOpen(false)}>編集を続ける</button>
    <button className="admin-button" disabled={busy} onClick={() => { if (!busy) window.location.assign("/admin/jobs"); }}>求人一覧へ戻る</button>
  </>}><p>未保存の変更は失われます。保存済みの通知は削除しません。</p></Modal> : null;
}

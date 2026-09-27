import type { ReactNode } from "react";
import { isStagingEnvironment } from "../lib/environment-policy";
import "./admin.css";
import { AdminAuthBoundary } from "./AdminAuthBoundary";

export default function AdminLayout({ children }: { children: ReactNode }) {
  const staging = isStagingEnvironment(process.env.APP_ENV);
  return <div className="admin-shell">
    <aside className="demo-notice" aria-label="デモ環境について">
      <strong>{staging ? "準本番検証環境" : "ローカルデモ環境"}</strong>
      <span>現在のLINE送信モードと送信可否を画面内で確認してください。送信時にはBackendでも再検証されます。</span>
    </aside>
    <AdminAuthBoundary required={process.env.APP_ENV === "production" || Boolean(process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID?.trim())}>
      {children}
    </AdminAuthBoundary>
  </div>;
}

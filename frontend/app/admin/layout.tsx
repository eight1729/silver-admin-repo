import type { ReactNode } from "react";
import { environmentLabel } from "../lib/environment-policy";
import "./admin.css";
import { AdminAuthBoundary } from "./AdminAuthBoundary";

export default function AdminLayout({ children }: { children: ReactNode }) {
  const label = environmentLabel(process.env.APP_ENV);
  return <div className="admin-shell">
    <aside className="demo-notice" aria-label="実行環境について">
      <strong>{label}</strong>
      <span>現在のLINE送信モードと送信可否を画面内で確認してください。送信時にはBackendでも再検証されます。</span>
    </aside>
    <AdminAuthBoundary>
      {children}
    </AdminAuthBoundary>
  </div>;
}

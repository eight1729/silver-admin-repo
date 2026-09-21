import type { ReactNode } from "react";
import { AdminHomeButton } from "./AdminHomeButton";
import { AdminEnvironmentProvider } from "./AdminEnvironment";
import { allowsDemoReset, isStagingEnvironment } from "../lib/environment-policy";
import "./admin.css";
import { AdminAuthBoundary } from "./AdminAuthBoundary";

export default function AdminLayout({ children }: { children: ReactNode }) {
  const staging = isStagingEnvironment(process.env.APP_ENV);
  const allowDemoReset = allowsDemoReset(process.env.APP_ENV);
  return <div className="admin-shell">
    <header className="admin-header admin-legacy-header" aria-hidden="true">
      <div><p className="admin-kicker">{staging ? "STAGING VERIFICATION" : "LOCAL DEMO"}</p><h1>求人通知デモ</h1></div>
      <AdminHomeButton />
    </header>
    <aside className="demo-notice" aria-label="デモ環境について">
      <strong>{staging ? "準本番検証環境" : "ローカルデモ環境"}</strong>
      <span>現在のLINE送信モードと送信可否を画面内で確認してください。送信時にはBackendでも再検証されます。</span>
    </aside>
    <AdminAuthBoundary required={process.env.APP_ENV === "production" || Boolean(process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID?.trim())}><AdminEnvironmentProvider allowDemoReset={allowDemoReset}>
      {children}
    </AdminEnvironmentProvider></AdminAuthBoundary>
  </div>;
}

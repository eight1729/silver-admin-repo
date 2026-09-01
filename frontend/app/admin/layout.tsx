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
      <span>業務データはモックです。Fakeモードでは現在は実LINE通知を送信しません。現在のLINE送信モードは画面内に表示されます。Backend再起動で一時データが初期化されます。</span>
    </aside>
    <AdminAuthBoundary><AdminEnvironmentProvider allowDemoReset={allowDemoReset}>
      {children}
    </AdminEnvironmentProvider></AdminAuthBoundary>
  </div>;
}

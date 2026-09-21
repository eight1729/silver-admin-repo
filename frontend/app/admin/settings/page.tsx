"use client";

import { modePresentation } from "../send-capability";

import { AdminRouteFrame } from "../AdminRouteFrame";
import { DEFAULT_CENTER_DISPLAY_NAME } from "../notification-templates";

export default function AdminSettingsPage() {
  return <AdminRouteFrame title="設定" description="画面で安全に確認できる非機密情報だけを表示します。">{(mode) => <div className="admin-route-grid"><section className="admin-card"><h3>表示情報</h3><dl className="compact-details"><div><dt>センター表示</dt><dd>{DEFAULT_CENTER_DISPLAY_NAME}</dd></div><div><dt>送信モード</dt><dd>{modePresentation(mode).label}</dd></div></dl></section><section className="admin-card"><h3>設定変更について</h3><p>認証情報、所属service、LINEチャネルはこの画面から変更できません。</p><p className="admin-muted">機密設定値は表示していません。</p></section></div>}</AdminRouteFrame>;
}

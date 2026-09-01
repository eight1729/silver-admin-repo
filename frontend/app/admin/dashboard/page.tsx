"use client";

import { AdminRouteFrame } from "../AdminRouteFrame";

export default function AdminDashboardPage() {
  return <AdminRouteFrame title="ダッシュボード" description="求人通知作成の入口と、現在利用できる機能を確認します。">{(mode) => <div className="admin-route-grid">
    <section className="admin-card"><h3>通知を作成</h3><p>求人と対象会員を選び、本文の検証後に通知を送信します。</p><a className="admin-button admin-inline-link" href="/admin">通知作成を開く</a></section>
    <section className="admin-card"><h3>現在の送信モード</h3><p className="admin-status">{mode?.mode === "staging_live" ? mode.ready ? "実LINE送信可能" : "実LINE送信ブロック中" : mode ? "Fake送信" : "確認中"}</p><p className="admin-muted">累計件数や全operationの集計は、取得手段がないため表示していません。</p></section>
  </div>}</AdminRouteFrame>;
}

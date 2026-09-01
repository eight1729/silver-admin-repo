import { AdminRouteFrame } from "../AdminRouteFrame";

export default function AdminReportsPage() {
  return <AdminRouteFrame title="レポート" description="取得可能な正本データに基づく集計を表示する画面です。"><section className="admin-card admin-route-placeholder"><h3>現在利用できるレポートはありません</h3><p>全operationの集計、開封、興味あり、辞退、応募に関する取得手段がないため、指標は表示していません。</p><p className="admin-muted">現在operationの配信結果は通知作成画面の「配信状況サマリー」で確認できます。</p><a className="admin-button admin-inline-link" href="/admin">配信状況を確認</a></section></AdminRouteFrame>;
}

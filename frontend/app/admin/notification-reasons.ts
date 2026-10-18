export function notificationReasonLabel(reason: string | null): string {
  if (!reason) return "—";
  return ({
    notification_opted_out: "就業通知の受信拒否（未送信）",
    notification_preferences_unanswered: "通知アンケート未回答（未送信）",
    notification_preferences_unavailable: "受信設定を確認できない（再検証が必要）",
    line_not_linked: "LINE未連携", recipient_not_linked: "LINE未連携",
    not_selected: "未選択", member_ineligible: "通知対象外",
    member_not_found: "会員情報を確認できません", member_no_longer_candidate: "現在の候補対象外",
    job_closed: "求人募集終了", job_version_changed: "求人情報更新あり",
    recipient_unavailable: "送信先を利用できません", recipient_identity_changed: "LINE連携が変更されています",
    line_temporary_error: "一時的な送信エラー", line_unknown_result: "送信結果不明",
    no_sendable_targets: "送信可能な対象者がいません",
  } as Record<string, string>)[reason] ?? "対象条件を確認してください";
}

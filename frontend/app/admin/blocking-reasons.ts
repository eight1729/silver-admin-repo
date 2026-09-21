import type { AdminLineSendMode } from "../lib/admin-api";

export const blockingReasonMessages = {
  sending_disabled: "LINE送信は無効です。",
  live_send_disabled: "実LINE送信は有効化されていません。",
  line_capability_unavailable: "LINE送信状態を確認できないため送信できません。",
  invalid_max_recipients: "実送信の送信人数設定が1名に固定されていません。",
  allowlist_missing: "検証対象者の許可設定が完了していません。",
  message_prefix_missing: "検証通知の識別表示が設定されていません。",
  access_token_missing: "LINE Messaging APIの送信設定が完了していません。",
  staff_authenticator_invalid: "準本番の管理者認証構成が正しくありません。",
  liff_url_invalid: "通知リンクの設定が正しくありません。",
} as const;

export type BlockingReasonCode = keyof typeof blockingReasonMessages;

const unknownBlockingReasonMessage = "実LINE送信の準備が完了していません。";

export function getBlockingReasonMessage(code: string): string {
  return Object.prototype.hasOwnProperty.call(blockingReasonMessages, code)
    ? blockingReasonMessages[code as BlockingReasonCode]
    : unknownBlockingReasonMessage;
}

export function formatBlockingReasons(mode: AdminLineSendMode | null): string[] {
  if (!mode || mode.ready === true) return [];
  return [...new Set((mode.blocking_reasons ?? []).map(getBlockingReasonMessage))];
}

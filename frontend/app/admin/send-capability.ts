import type { AdminLineSendMode } from "../lib/admin-api";

export function isLiveMode(mode: AdminLineSendMode | null) {
  return mode?.mode === "staging_live" || mode?.mode === "production_live";
}

export function canAttemptSend(mode: AdminLineSendMode | null, sendableCount = 0) {
  if (!mode || mode.ready !== true || mode.blocking_reasons?.length) return false;
  if (mode.mode !== "fake" && (!isLiveMode(mode) || mode.live_send_enabled !== true)) return false;
  return mode.max_recipients == null || sendableCount <= mode.max_recipients;
}

export function safetyPrefix(mode: AdminLineSendMode | null) {
  return mode?.mode === "staging_live" ? mode.message_prefix ?? "" : "";
}

export function modePresentation(mode: AdminLineSendMode | null) {
  if (mode?.mode === "fake") return { label: "Fake", detail: "実LINE送信なし", tone: "fake" };
  if (mode?.mode === "disabled") return { label: "LINE送信は無効", detail: "実LINE送信は行いません", tone: "blocked" };
  if (!mode || mode.mode === "unavailable") return { label: "LINE送信状態を確認できません", detail: "状態を確認できないため送信不可", tone: "blocked" };
  if (!canAttemptSend(mode)) return { label: "LINE送信設定未完了", detail: "現在は送信できません", tone: "blocked" };
  if (mode.mode === "staging_live") return { label: "限定実LINE送信", detail: mode.max_recipients == null ? "LINE側の許可対象に限定" : `最大${mode.max_recipients}名・LINE側の許可対象に限定`, tone: "ready" };
  return { label: "実LINE送信", detail: "実際にLINE通知を送信します", tone: "ready" };
}

export function sendWarning(mode: AdminLineSendMode | null) {
  const presentation = modePresentation(mode);
  return `${presentation.label}：${presentation.detail}${isLiveMode(mode) && canAttemptSend(mode) ? "。送信後は取り消せません。" : "。"}`;
}

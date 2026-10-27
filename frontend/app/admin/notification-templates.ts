import type { AdminMessage } from "../lib/admin-api";

export const DEFAULT_CENTER_DISPLAY_NAME = "【未入力：センター名】";
export const CENTER_DISPLAY_NAME_MAX_LENGTH = 80;
const MESSAGE_COMPAT_PLACEHOLDER = "\u2063";
const TEMPLATE_CLOSING = "ほかにもおすすめのお仕事があります。\nその他のお仕事はLINEミニアプリからご確認ください。";

const STANDARD_CLOSING = "━━━━━━━━━━━━\nご希望の方は、下の「電話する」ボタンからセンターへご連絡ください。\n\nその他の仕事は↓メニュー「求人中のお仕事」からご確認ください。";

export function hasUnfilledNotificationFields(message: AdminMessage): boolean {
  return Object.values(message).some(value => value.replace(/\u2063/g, "").split(/\r\n|[\n\r\u2028\u2029]/).some((line: string) =>
    /^[ \t　]*【未入力：(センター名|仕事内容|働く場所|働く日|時間|配分金|募集人数)】(?:です。)?[ \t　]*$/.test(line)));
}

export type NotificationTemplateId = "standard" | "urgent" | "reminder" | "personal" | "blank";
export type SelectedTemplateId = NotificationTemplateId | "custom";

export interface NotificationTemplateJob {
  title: string;
  location?: string | null;
  description?: string | null;
  workTime?: string | null;
  workDays?: string | null;
  summary?: string | null;
}

export const notificationTemplates: ReadonlyArray<{ id: NotificationTemplateId; label: string; requiresJob: boolean }> = [
  { id: "standard", label: "標準案内", requiresJob: true },
  { id: "urgent", label: "急募", requiresJob: true },
  { id: "reminder", label: "再案内", requiresJob: true },
  { id: "personal", label: "個別案内", requiresJob: true },
  { id: "blank", label: "白紙", requiresJob: false },
];

export function notificationBody(message: AdminMessage): string {
  if (message.introduction === MESSAGE_COMPAT_PLACEHOLDER) return message.greeting;
  return [message.greeting, message.introduction].filter((value) => value.trim()).join("\n\n");
}

export function composeAdminMessage(body: string, note: string): AdminMessage {
  return { greeting: body, introduction: MESSAGE_COMPAT_PLACEHOLDER, note };
}

function composeTemplateMessage(body: string): AdminMessage {
  return composeAdminMessage(body, MESSAGE_COMPAT_PLACEHOLDER);
}

export function notificationDisplayText(message: AdminMessage): string {
  const note = message.note === MESSAGE_COMPAT_PLACEHOLDER ? "" : message.note;
  return [notificationBody(message), note].filter((value) => value.trim()).join("\n\n");
}

function clean(value?: string | null): string {
  return value?.trim() ?? "";
}

function templateHeading(templateId: Exclude<NotificationTemplateId, "blank">, title: string): string {
  if (templateId === "urgent") return `【急募：${title}】`;
  if (templateId === "reminder") return `【再案内：${title}】`;
  if (templateId === "personal") return `【個別案内：${title}】`;
  return `【${title}の求人お知らせについて】`;
}

function templateLead(templateId: Exclude<NotificationTemplateId, "blank">): string {
  if (templateId === "urgent") return "下記の求人を急ぎご案内します。\nご興味のある方は、早めに詳細をご確認ください。";
  if (templateId === "reminder") return "以前ご案内した下記の求人を、改めてお知らせします。\nご興味のある方は、詳細をご確認ください。";
  if (templateId === "personal") return "条件に合う可能性のある下記の求人を、個別にご案内します。\nご興味のある方は、詳細をご確認ください。";
  return "下記の求人をご案内します。\nご興味のある方は、詳細をご確認ください。";
}

export function createTemplateMessage(
  templateId: NotificationTemplateId,
  centerName: string,
  job?: NotificationTemplateJob | null,
  notice = "",
): AdminMessage {
  if (templateId === "blank") return composeAdminMessage("", "");
  const title = clean(job?.title);
  const center = clean(centerName);
  if (templateId === "standard") {
    const field = (label: string, value?: string | null) => clean(value) || `【未入力：${label}】`;
    const body = [
      `■就業案内
【お仕事のご案内】
いつもお世話になっております。
${center || DEFAULT_CENTER_DISPLAY_NAME}です。
下記の求人をご案内します。`,
      `◆ お仕事の内容
　${field("仕事内容", job?.description)}`,
      `◆ 働く場所
　${field("働く場所", job?.location)}`,
      `◆ 働く日
　${field("働く日", job?.workDays)}`,
      `◆ 時間
　${field("時間", job?.workTime)}`,
      `◆ 配分金
　${field("配分金")}`,
      `◆ 募集人数
　${field("募集人数")}`,
    ].join("\n\n");
    return composeTemplateMessage(`${body}${clean(notice) ? `\n\n${clean(notice)}` : ""}\n${STANDARD_CLOSING}`);
  }
  const details = [
    ["就業内容", clean(job?.description)],
    ["勤務時間", clean(job?.workTime)],
    ["勤務日", clean(job?.workDays)],
    ["概要", clean(job?.summary)],
  ].filter((item): item is [string, string] => Boolean(item[1])).map(([label, value]) => `${label}）${value}`);
  const sections = [
    templateHeading(templateId, title),
    ["いつもお世話になっております。", center ? `${center}です。` : ""].filter(Boolean).join("\n"),
    templateLead(templateId),
    details.join("\n"),
    clean(notice),
    TEMPLATE_CLOSING,
  ].filter((section) => section.trim());
  return composeTemplateMessage(sections.join("\n\n"));
}

export function notificationNotice(message: AdminMessage): string {
  if (message.note !== MESSAGE_COMPAT_PLACEHOLDER) return message.note;
  const body = notificationBody(message);
  const standardEnd = body.lastIndexOf(`\n${STANDARD_CLOSING}`);
  if (standardEnd >= 0) {
    const recruitment = body.lastIndexOf("◆ 募集人数\n", standardEnd);
    if (recruitment < 0) return "";
    const noticeAt = body.indexOf("\n\n", recruitment);
    return noticeAt >= 0 && noticeAt < standardEnd ? body.slice(noticeAt + 2, standardEnd).trim() : "";
  }
  const closingAt = body.lastIndexOf(`\n\n${TEMPLATE_CLOSING}`);
  if (closingAt < 0) return "";
  const sections = body.slice(0, closingAt).split("\n\n");
  const afterLead = sections.slice(3);
  if (afterLead[0]?.split("\n").every((line) => /^(?:就業内容|勤務時間|勤務日|概要）)/.test(line))) afterLead.shift();
  return afterLead.join("\n\n").trim();
}

export function replaceExactNotice(message: AdminMessage, previousNotice: string, nextNotice: string): AdminMessage {
  const body = notificationBody(message);
  const previous = previousNotice.trim();
  const next = nextNotice.trim();
  if (previous === next) return { ...message };
  if (message.note !== MESSAGE_COMPAT_PLACEHOLDER) return { ...message, note: next };
  if (previous && body.includes(`\n\n${previous}\n${STANDARD_CLOSING}`)) {
    return composeTemplateMessage(body.replace(`\n\n${previous}\n${STANDARD_CLOSING}`, `${next ? `\n\n${next}` : ""}\n${STANDARD_CLOSING}`));
  }
  if (previous && body.includes(previous)) return composeTemplateMessage(body.replace(previous, next).replace(/\n{3,}/g, "\n\n"));
  const closing = body.includes(`\n${STANDARD_CLOSING}`) ? `\n${STANDARD_CLOSING}` : `\n\n${TEMPLATE_CLOSING}`;
  if (!previous && next && body.includes(closing)) return composeTemplateMessage(body.replace(closing, `\n\n${next}${closing}`));
  return { ...message };
}

export function replaceExactCenterName(message: AdminMessage, previousName: string, nextName: string): AdminMessage {
  if (!previousName || previousName === nextName) return { ...message };
  return {
    greeting: message.greeting.split(previousName).join(nextName),
    introduction: message.introduction.split(previousName).join(nextName),
    note: message.note.split(previousName).join(nextName),
  };
}

import type { AdminMessage, AdminLineSendMode } from "../lib/admin-api";

export function finalNotificationText(message: AdminMessage, link: string | null, mode: AdminLineSendMode | null): string | null {
  if (!link || !mode || !["staging_live", "production_live"].includes(mode.mode)) return null;
  let greeting = message.greeting;
  if (mode.mode === "staging_live") {
    const prefix = mode.message_prefix?.trim();
    if (!prefix) return null;
    while (greeting.startsWith(prefix)) greeting = greeting.slice(prefix.length).trimStart();
    greeting = `${prefix}\n\n${greeting}`;
  }
  return [greeting, message.introduction, message.note, link].join("\n\n");
}

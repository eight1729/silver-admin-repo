import type { AdminDeliveries, DeliveryStatus } from "../lib/admin-api";

export const deliveryStatusPresentation: ReadonlyArray<{ status: DeliveryStatus; label: string; color: string }> = [
  { status: "sent", label: "送信済み", color: "#2f7d5c" },
  { status: "failed", label: "送信失敗", color: "#b44d4d" },
  { status: "unknown", label: "結果不明", color: "#a96d16" },
  { status: "skipped", label: "対象外", color: "#68747d" },
  { status: "pending", label: "処理待ち", color: "#8d9aa3" },
];

export interface DeliverySummaryItem { status: DeliveryStatus; label: string; color: string; count: number }

export function summarizeDeliveries(deliveries: AdminDeliveries) {
  const unique = new Map(deliveries.items.map((delivery) => [delivery.delivery_id, delivery]));
  const counts = Object.fromEntries(deliveryStatusPresentation.map(({ status }) => [status, 0])) as Record<DeliveryStatus, number>;
  for (const delivery of unique.values()) counts[delivery.status] += 1;
  const items: DeliverySummaryItem[] = deliveryStatusPresentation.map((item) => ({ ...item, count: counts[item.status] }));
  return { total: unique.size, items };
}

export function createDeliveryGradient(items: readonly DeliverySummaryItem[], total: number): string {
  if (total === 0) return "none";
  let cursor = 0;
  const segments: string[] = [];
  for (const item of items) {
    if (item.count === 0) continue;
    const start = cursor;
    cursor += (item.count / total) * 100;
    segments.push(`${item.color} ${start}% ${cursor}%`);
  }
  return `conic-gradient(${segments.join(", ")})`;
}

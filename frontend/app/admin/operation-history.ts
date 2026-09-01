import type { AdminDeliveries, AdminOperation } from "../lib/admin-api";

export interface SessionHistoryEvent {
  id: string;
  operationId: string;
  jobName: string;
  name: string;
  status: string;
  occurredAt: string;
  description: string;
}

export interface OperationHistoryItem extends SessionHistoryEvent {}

export function buildOperationHistory(operation: AdminOperation | null, jobName: string | null, deliveries: AdminDeliveries | null, sessionEvents: readonly SessionHistoryEvent[], maximum = 8): OperationHistoryItem[] {
  if (!operation) return [];
  const title = jobName ?? "求人名を取得できません";
  const items: OperationHistoryItem[] = sessionEvents.filter((item) => item.operationId === operation.operation_id).map((item) => ({ ...item }));
  items.push({ id: `created-${operation.operation_id}`, operationId: operation.operation_id, jobName: title, name: "通知作成", status: "作成済み", occurredAt: operation.created_at, description: "現在の通知operationが作成されました。" });
  if (operation.validated_at) {
    const validationPassed = operation.status !== "blocked_external_system";
    items.push({ id: `validated-${operation.operation_id}`, operationId: operation.operation_id, jobName: title, name: "事前検証", status: validationPassed ? "検証済み" : "検証不成立", occurredAt: operation.validated_at, description: validationPassed ? "送信前の検証が完了しました。" : "送信条件を満たさない検証結果でした。" });
  }
  if (operation.send_requested_at) items.push({ id: `requested-${operation.operation_id}`, operationId: operation.operation_id, jobName: title, name: "送信受付", status: "受付済み", occurredAt: operation.send_requested_at, description: "送信処理が受け付けられました。" });
  if (operation.completed_at) items.push({ id: `completed-${operation.operation_id}`, operationId: operation.operation_id, jobName: title, name: "送信処理", status: operation.status === "completed" ? "完了" : "一部エラーで完了", occurredAt: operation.completed_at, description: "現在のoperationの送信処理が完了しました。" });
  const uniqueDeliveries = new Map((deliveries?.items ?? []).map((delivery) => [delivery.delivery_id, delivery]));
  for (const delivery of uniqueDeliveries.values()) {
    if (delivery.status === "pending") continue;
    const occurredAt = delivery.sent_at ?? delivery.updated_at;
    const presentation = ({ sent: ["配信結果", "送信済み"], failed: ["配信結果", "送信失敗"], unknown: ["配信結果", "結果不明"], skipped: ["配信結果", "対象外"] } as const)[delivery.status];
    items.push({ id: `delivery-${delivery.delivery_id}`, operationId: operation.operation_id, jobName: title, name: presentation[0], status: presentation[1], occurredAt, description: delivery.status === "unknown" ? "送信結果を確定できません。自動再送は行われません。" : "現在のoperationに属する配信結果です。" });
  }
  return items.filter((item) => Boolean(Date.parse(item.occurredAt))).sort((left, right) => Date.parse(right.occurredAt) - Date.parse(left.occurredAt)).slice(0, Math.max(0, maximum));
}

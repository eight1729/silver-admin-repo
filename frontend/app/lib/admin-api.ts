import { ADMIN_API_BASE } from "./admin-config";

export type JobStatus = "draft" | "published" | "closed" | "suspended";
export type NotificationType = "new_job_match" | "existing_job_match" | "custom_job";
export type OperationStatus = "draft" | "validating" | "ready" | "blocked_external_system" | "sending" | "completed" | "completed_with_errors" | "cancelled";
export type DeliveryStatus = "pending" | "sent" | "failed" | "unknown" | "skipped";

export interface AdminJobSummary { job_id: string; title: string; location: string | null; status: JobStatus; openings: number; version: string; summary: string | null; work_days?: string | null; work_time?: string | null }
export interface AdminJobDetail { job_id: string; title: string; description: string; location: string | null; conditions: string[]; status: JobStatus; openings: number; version: string; job_url: string; contact: string | null }
export interface AdminCandidate { member_id: string; display_name: string; line_linked: boolean; eligible: boolean; reason: string | null; selected: boolean; preference_summary?: string | null }
export interface AdminMessage { greeting: string; introduction: string; note: string }
export interface AdminOperation { operation_id: string; job_id: string; job_version: string | null; notification_type: NotificationType; message: AdminMessage; status: OperationStatus; target_count: number; selected_count: number; validated_at: string | null; send_requested_at: string | null; completed_at: string | null; created_at: string; updated_at: string }
export interface AdminValidation { operation_id: string; status: OperationStatus; can_proceed: boolean; selected_count: number; sendable_count: number; skipped_count: number; reasons: string[]; version_changed: boolean; external_system_blocked: boolean }
export interface AdminDelivery { delivery_id: string; member_id: string; status: DeliveryStatus; reason_code: string | null; created_at: string; sent_at: string | null; updated_at: string }
export interface AdminDeliveries { items: AdminDelivery[]; summary: Record<DeliveryStatus, number> }
export interface AdminLineSendMode { mode: "fake" | "disabled" | "staging_live" | "production_live" | "unavailable"; max_recipients: number | null; message_prefix: string | null; live_send_enabled?: boolean | null; ready?: boolean | null; blocking_reasons?: string[] }

export class AdminApiError extends Error {
  constructor(public readonly status: number, public readonly code: string) { super(code); }
}

type AdminAccessTokenProvider = () => string | null | Promise<string | null>;
let accessTokenProvider: AdminAccessTokenProvider | null = null;

export function registerAdminAccessTokenProvider(provider: AdminAccessTokenProvider | null) {
  accessTokenProvider = provider;
}

async function request<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  if (!ADMIN_API_BASE) throw new AdminApiError(0, "api_not_configured");
  let response: Response;
  try {
    const accessToken = accessTokenProvider ? await accessTokenProvider() : null;
    response = await fetch(`${ADMIN_API_BASE}${path}`, {
      ...init,
      signal,
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...(process.env.NEXT_PUBLIC_ADMIN_SERVICE_ID ? { "X-Service-ID": process.env.NEXT_PUBLIC_ADMIN_SERVICE_ID } : {}),
        ...init.headers,
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new AdminApiError(0, "network_error");
  }
  if (!response.ok) {
    let code = "request_failed";
    try {
      const body = (await response.json()) as { detail?: { error?: string } };
      if (typeof body.detail?.error === "string") code = body.detail.error;
    } catch { /* Never expose a raw response. */ }
    const error = new AdminApiError(response.status, code);
    if (response.status === 401 || response.status === 403) {
      globalThis.dispatchEvent?.(new CustomEvent("admin-auth-failure", { detail: { status: response.status } }));
    }
    throw error;
  }
  return response.json() as Promise<T>;
}

export const adminApi = {
  lineSendMode: (signal?: AbortSignal) => request<AdminLineSendMode>("/admin/line-send-mode", {}, signal),
  jobs: (signal?: AbortSignal) => request<AdminJobSummary[]>("/admin/jobs", {}, signal),
  job: (id: string, signal?: AbortSignal) => request<AdminJobDetail>(`/admin/jobs/${encodeURIComponent(id)}`, {}, signal),
  notificationLink: (id: string, signal?: AbortSignal) => request<{ url: string }>(`/admin/jobs/${encodeURIComponent(id)}/notification-link`, {}, signal),
  candidates: (id: string, signal?: AbortSignal) => request<AdminCandidate[]>(`/admin/jobs/${encodeURIComponent(id)}/candidates`, {}, signal),
  createOperation: (body: { job_id: string; notification_type: NotificationType; greeting: string; introduction: string; note: string }) => request<AdminOperation>("/admin/notification-operations", { method: "POST", body: JSON.stringify(body) }),
  operation: (id: string, signal?: AbortSignal) => request<AdminOperation>(`/admin/notification-operations/${encodeURIComponent(id)}`, {}, signal),
  updateOperation: (id: string, body: AdminMessage) => request<AdminOperation>(`/admin/notification-operations/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(body) }),
  updateTargets: (id: string, selected: string[]) => request<AdminOperation>(`/admin/notification-operations/${encodeURIComponent(id)}/targets`, { method: "PUT", body: JSON.stringify({ selected_member_ids: [...new Set(selected)] }) }),
  validate: (id: string) => request<AdminValidation>(`/admin/notification-operations/${encodeURIComponent(id)}/validate`, { method: "POST" }),
  send: (id: string) => request<AdminOperation>(`/admin/notification-operations/${encodeURIComponent(id)}/send`, { method: "POST" }),
  deliveries: (id: string, signal?: AbortSignal) => request<AdminDeliveries>(`/admin/notification-operations/${encodeURIComponent(id)}/deliveries`, {}, signal),
  reset: () => request<{ reset: boolean }>("/admin/demo/reset", { method: "POST" }),
};

export function adminErrorMessage(error: unknown): string {
  if (!(error instanceof AdminApiError)) return "処理に失敗しました。もう一度お試しください。";
  if (error.code === "api_not_configured") return "Backend URLが設定されていません。ローカル環境の設定を確認してください。";
  if (error.code === "external_system_unavailable") return "求人・候補情報を確認できませんでした。しばらくして再確認してください。";
  if (error.code === "staff_auth_unavailable") return "デモ用スタッフ情報を取得できませんでした。";
  if (error.status === 401) return "認証が必要です。ログイン状態を確認してください。";
  if (error.status === 403) return "この操作を行う権限、またはサービス利用権限がありません。";
  if (error.status === 404) return "対象が見つかりません。求人一覧から選び直してください。";
  if (error.status === 409) return "状態が変更されています。最新状態を再確認してください。";
  if (error.status === 422) return "入力内容を確認してください。";
  if (error.status === 503 || error.status === 0) return "デモ用Backendを一時的に利用できません。しばらくして再試行してください。";
  return "処理に失敗しました。もう一度お試しください。";
}

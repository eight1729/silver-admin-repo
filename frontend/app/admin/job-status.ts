import type { JobStatus } from "../lib/admin-api";

const jobStatusLabels: Record<JobStatus, string> = {
  draft: "下書き",
  published: "募集中",
  paused: "停止中",
  closed: "募集終了",
  cancelled: "取消",
  unknown: "状態不明",
};

export function jobStatusLabel(status: JobStatus): string {
  return jobStatusLabels[status] ?? jobStatusLabels.unknown;
}

import type { AdminMessage, AdminOperation, AdminValidation } from "../lib/admin-api";

export interface ValidationInput {
  jobId: string | null;
  selectedMemberIds: string[];
  message: AdminMessage;
  notificationLink: string | null;
  operationId: string | null;
  centerDisplayName: string;
}

export interface ValidationSnapshot extends ValidationInput {}

export type WorkflowAction = "idle" | "saving" | "validating" | "sending";
export type NotificationUiState = "initial" | "editing" | "validatable" | "validated" | "validation_failed" | "stale" | "sending" | "sent" | "blocked";

export function createValidationSnapshot(input: ValidationInput): ValidationSnapshot {
  return {
    jobId: input.jobId,
    selectedMemberIds: [...new Set(input.selectedMemberIds)].sort(),
    message: { ...input.message },
    notificationLink: input.notificationLink,
    operationId: input.operationId,
    centerDisplayName: input.centerDisplayName,
  };
}

export function isValidationSnapshotCurrent(snapshot: ValidationSnapshot | null, input: ValidationInput): boolean {
  if (!snapshot) return false;
  const current = createValidationSnapshot(input);
  return snapshot.jobId === current.jobId
    && snapshot.operationId === current.operationId
    && snapshot.notificationLink === current.notificationLink
    && snapshot.centerDisplayName === current.centerDisplayName
    && snapshot.selectedMemberIds.length === current.selectedMemberIds.length
    && snapshot.selectedMemberIds.every((value, index) => value === current.selectedMemberIds[index])
    && messagesEqual(snapshot.message, current.message);
}

export function messagesEqual(left: AdminMessage, right: AdminMessage): boolean {
  return left.greeting === right.greeting && left.introduction === right.introduction && left.note === right.note;
}

export function memberSelectionsEqual(left: Iterable<string>, right: Iterable<string>): boolean {
  const leftValues = [...new Set(left)].sort();
  const rightValues = [...new Set(right)].sort();
  return leftValues.length === rightValues.length && leftValues.every((value, index) => value === rightValues[index]);
}

export function isTerminalOperation(operation: AdminOperation | null): boolean {
  return operation?.status === "completed" || operation?.status === "completed_with_errors" || operation?.status === "cancelled";
}

export function deriveNotificationUiState(args: {
  hasJob: boolean;
  selectedCount: number;
  messageValid: boolean;
  operation: AdminOperation | null;
  validation: AdminValidation | null;
  validationCurrent: boolean;
  validationWasInvalidated: boolean;
  busy: boolean;
  action: WorkflowAction;
  liveBlocked: boolean;
  liveLinkReady: boolean;
  hasTerminalDelivery: boolean;
  queueFailure: boolean;
}) {
  const terminal = isTerminalOperation(args.operation) || args.hasTerminalDelivery;
  const canSaveDraft = args.hasJob && args.messageValid && Boolean(args.operation) && !args.busy && !terminal;
  const canValidate = args.hasJob && args.selectedCount === 1 && args.messageValid && Boolean(args.operation) && !args.busy && !terminal && args.liveLinkReady;
  const canSend = canValidate
    && args.action === "idle"
    && args.operation?.status === "ready"
    && args.validation?.can_proceed === true
    && args.validation.selected_count === 1
    && args.validation.sendable_count === 1
    && args.validationCurrent
    && !args.liveBlocked
    && args.liveLinkReady
    && !args.queueFailure;

  let state: NotificationUiState;
  if (terminal) state = "sent";
  else if (args.action === "sending" || args.operation?.status === "sending") state = "sending";
  else if (args.liveBlocked || args.operation?.status === "blocked_external_system") state = "blocked";
  else if (args.validationWasInvalidated || (args.validation && !args.validationCurrent)) state = "stale";
  else if (args.validation?.can_proceed && args.validationCurrent) state = "validated";
  else if (args.validation && args.validationCurrent) state = "validation_failed";
  else if (canValidate) state = "validatable";
  else if (args.hasJob || args.operation) state = "editing";
  else state = "initial";

  return { state, canSaveDraft, canValidate, canSend, terminal } as const;
}

export function uiStatePresentation(state: NotificationUiState) {
  return ({
    initial: { label: "初期", description: "求人、対象会員、通知本文を順に準備してください。" },
    editing: { label: "編集中", description: "入力内容を保存し、送信前に検証してください。" },
    validatable: { label: "検証可能", description: "必要な内容が揃っています。保存して検証できます。" },
    validated: { label: "検証済み", description: "現在の内容に対する検証が完了しています。" },
    validation_failed: { label: "検証不成立", description: "現在の内容は送信条件を満たしていません。表示された理由を確認してください。" },
    stale: { label: "再検証が必要", description: "内容が変更されたため、再検証が必要です。" },
    sending: { label: "送信中", description: "送信処理中です。ほかの操作は行わないでください。" },
    sent: { label: "送信済み", description: "この通知operationは送信済みです。再送できません。" },
    blocked: { label: "送信ブロック中", description: "現在の状態では送信できません。表示された理由を確認してください。" },
  } as const)[state];
}

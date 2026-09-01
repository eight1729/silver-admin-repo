import assert from "node:assert/strict";
import test from "node:test";

import { clearedTransientAdminState, createOrSaveTargets, reloadDeliveryResults, restoreAdminOperation, saveThenValidate, sendThenLoadDeliveries } from "./admin-workflow.ts";
import type { AdminCandidate, AdminDeliveries, AdminJobDetail, AdminOperation, AdminValidation } from "../lib/admin-api.ts";

class TestApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string) { super(code); this.status = status; this.code = code; }
}

const operation = (overrides: Partial<AdminOperation> = {}): AdminOperation => ({
  operation_id: "op-1", job_id: "JOB-001", job_version: "v1", notification_type: "new_job_match",
  message: { greeting: "saved greeting", introduction: "saved introduction", note: "saved note" },
  status: "draft", target_count: 0, selected_count: 0, validated_at: null,
  send_requested_at: null, completed_at: null, created_at: "2026-08-04T00:00:00Z",
  updated_at: "2026-08-04T00:00:00Z", ...overrides,
});

const validation: AdminValidation = {
  operation_id: "op-1", status: "ready", can_proceed: true, selected_count: 1,
  sendable_count: 1, skipped_count: 0, reasons: [], version_changed: false,
  external_system_blocked: false,
};

test("editing then validate saves the current message before validation", async () => {
  const calls: string[] = [];
  const edited = { greeting: "edited", introduction: "edited body", note: "edited note" };
  const result = await saveThenValidate({
    operationId: "op-1", message: edited,
    save: async (_id, message) => { calls.push(`save:${message.greeting}`); return operation({ message }); },
    validate: async () => { calls.push("validate"); return validation; },
  });
  assert.deepEqual(calls, ["save:edited", "validate"]);
  assert.deepEqual(result.operation.message, edited);
});

test("validation is not called when saving the edited message fails", async () => {
  let validateCalls = 0;
  await assert.rejects(saveThenValidate({
    operationId: "op-1", message: operation().message,
    save: async () => { throw new Error("safe mock failure"); },
    validate: async () => { validateCalls += 1; return validation; },
  }));
  assert.equal(validateCalls, 0);
});

test("partial create keeps the operation and retry only saves targets", async () => {
  let retained: AdminOperation | null = null;
  let retainedId = "";
  let createCalls = 0;
  let targetCalls = 0;
  const args = {
    jobId: "JOB-001", createBody: { job_id: "JOB-001", notification_type: "new_job_match" as const, ...operation().message },
    selectedMemberIds: ["M001", "M001"],
    create: async () => { createCalls += 1; return operation(); },
    saveTargets: async (_id: string, ids: string[]) => {
      targetCalls += 1; assert.deepEqual(ids, ["M001"]);
      if (targetCalls === 1) throw new Error("safe mock failure");
      return operation({ target_count: 1, selected_count: 1 });
    },
    reload: async () => operation({ target_count: 1, selected_count: 1 }),
    onCreated: (created: AdminOperation) => { retained = created; retainedId = created.operation_id; },
  };
  await assert.rejects(createOrSaveTargets({ ...args, operation: retained }));
  assert.equal(retainedId, "op-1");
  await createOrSaveTargets({ ...args, operation: retained });
  assert.equal(createCalls, 1);
  assert.equal(targetCalls, 2);
});

test("send success remains successful when deliveries fail", async () => {
  const calls: string[] = [];
  let shownStatus = "";
  const result = await sendThenLoadDeliveries({
    operationId: "op-1",
    send: async () => { calls.push("send"); return operation({ status: "completed", completed_at: "2026-08-04T01:00:00Z" }); },
    loadDeliveries: async () => { calls.push("deliveries"); throw new Error("safe mock failure"); },
    onSent: (sent) => { calls.push("show-result"); shownStatus = sent.status; },
  });
  assert.deepEqual(calls, ["send", "show-result", "deliveries"]);
  assert.equal(shownStatus, "completed");
  assert.equal(result.deliveries, null);
  assert.ok(result.deliveryError);
});

test("delivery retry calls getDeliveries once and never calls sendOperation", async () => {
  let sendCalls = 0;
  let deliveryCalls = 0;
  const completed = operation({ status: "completed_with_errors" });
  const response: AdminDeliveries = { items: [], summary: { pending: 0, sent: 0, failed: 1, unknown: 0, skipped: 0 } };
  const result = await reloadDeliveryResults({
    operation: completed,
    actions: {
      sendOperation: async () => { sendCalls += 1; return completed; },
      getDeliveries: async () => { deliveryCalls += 1; return response; },
    },
  });
  assert.equal(result.deliveries?.summary.failed, 1);
  assert.equal(result.operation.status, "completed_with_errors");
  assert.equal(sendCalls, 0);
  assert.equal(deliveryCalls, 1);
});

test("failed delivery retry preserves operation status without sending", async () => {
  let sendCalls = 0;
  const completed = operation({ status: "completed" });
  const result = await reloadDeliveryResults({
    operation: completed,
    actions: {
      sendOperation: async () => { sendCalls += 1; return completed; },
      getDeliveries: async () => { throw new Error("safe mock failure"); },
    },
  });
  assert.equal(result.operation.status, "completed");
  assert.ok(result.deliveryError);
  assert.equal(sendCalls, 0);
});

const job: AdminJobDetail = { job_id: "JOB-001", title: "Demo", description: "Demo", location: null, conditions: [], status: "published", openings: 1, version: "v1", job_url: "https://demo.invalid/job", contact: null };
const candidates: AdminCandidate[] = [{ member_id: "M001", display_name: "Demo member", line_linked: true, eligible: true, reason: null, selected: false }];
const deliveryResponse: AdminDeliveries = { items: [], summary: { pending: 0, sent: 1, failed: 0, unknown: 0, skipped: 0 } };

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => { resolve = complete; });
  return { promise, resolve };
}

function restore(overrides: Partial<Parameters<typeof restoreAdminOperation>[0]> = {}) {
  let removed = 0;
  const promise = restoreAdminOperation({
    operationId: "op-1", getOperation: async () => operation(), onOperationRestored: () => {}, getJob: async () => job,
    getCandidates: async () => candidates,
    deliveryActions: { sendOperation: async () => operation(), getDeliveries: async () => deliveryResponse },
    isNotFound: (e) => e instanceof TestApiError && e.status === 404,
    removeStoredOperationId: () => { removed += 1; }, ...overrides,
  });
  return { promise, removed: () => removed };
}

test("job failure preserves the restored operation and stored ID", async () => {
  const run = restore({ getJob: async () => { throw new TestApiError(503, "service_unavailable"); } });
  const result = await run.promise;
  assert.equal(result.operation?.operation_id, "op-1");
  assert.ok(result.jobError);
  assert.equal(run.removed(), 0);
});

test("operation is reported before a pending job request resolves", async () => {
  const pendingJob = deferred<AdminJobDetail>();
  const restored = deferred<void>();
  const events: string[] = [];
  const run = restore({
    onOperationRestored: (_operation, step) => { events.push(`operation:${step}`); restored.resolve(); },
    getJob: async () => { events.push("job:start"); return pendingJob.promise; },
  });
  await restored.promise;
  assert.deepEqual(events, ["operation:edit", "job:start"]);
  pendingJob.resolve(job);
  await run.promise;
});

test("operation is reported before a pending candidates request resolves", async () => {
  const pendingCandidates = deferred<AdminCandidate[]>();
  const restored = deferred<void>();
  const events: string[] = [];
  const run = restore({
    onOperationRestored: (_operation, step) => { events.push(`operation:${step}`); restored.resolve(); },
    getCandidates: async () => { events.push("candidates:start"); return pendingCandidates.promise; },
  });
  await restored.promise;
  assert.deepEqual(events, ["operation:edit", "candidates:start"]);
  pendingCandidates.resolve(candidates);
  await run.promise;
});

test("completed operation and result step are reported before deliveries resolve", async () => {
  const pendingDeliveries = deferred<AdminDeliveries>();
  const restored = deferred<void>();
  const events: string[] = [];
  const completed = operation({ status: "completed" });
  const run = restore({
    getOperation: async () => completed,
    onOperationRestored: (restoredOperation, step) => {
      events.push(`${restoredOperation.status}:${step}`); restored.resolve();
    },
    deliveryActions: {
      sendOperation: async () => { throw new Error("send must not run"); },
      getDeliveries: async () => { events.push("deliveries:start"); return pendingDeliveries.promise; },
    },
  });
  await restored.promise;
  assert.deepEqual(events, ["completed:result", "deliveries:start"]);
  pendingDeliveries.resolve(deliveryResponse);
  await run.promise;
});

test("candidate failure preserves the restored operation and stored ID", async () => {
  const run = restore({ getCandidates: async () => { throw new TestApiError(503, "service_unavailable"); } });
  const result = await run.promise;
  assert.equal(result.operation?.operation_id, "op-1");
  assert.ok(result.candidatesError);
  assert.equal(run.removed(), 0);
});

test("completed restore preserves status and ID when deliveries fail", async () => {
  let sendCalls = 0;
  const run = restore({
    getOperation: async () => operation({ status: "completed" }),
    deliveryActions: {
      sendOperation: async () => { sendCalls += 1; return operation(); },
      getDeliveries: async () => { throw new TestApiError(503, "service_unavailable"); },
    },
  });
  const result = await run.promise;
  assert.equal(result.operation?.status, "completed");
  assert.ok(result.deliveryError);
  assert.equal(run.removed(), 0);
  assert.equal(sendCalls, 0);
});

test("only an operation 404 removes the stored operation ID", async () => {
  const run = restore({ getOperation: async () => { throw new TestApiError(404, "resource_not_found"); } });
  const result = await run.promise;
  assert.equal(result.operation, null);
  assert.equal(run.removed(), 1);
});

test("temporary operation failure keeps the stored operation ID", async () => {
  const run = restore({ getOperation: async () => { throw new TestApiError(503, "service_unavailable"); } });
  await run.promise;
  assert.equal(run.removed(), 0);
});

test("return-to-jobs transient state clears previous job-specific state", () => {
  const cleared = clearedTransientAdminState();
  assert.equal(cleared.targetsPending, false);
  assert.equal(cleared.selectedJobId, null);
  assert.equal(cleared.validation, null);
  assert.equal(cleared.deliveries, null);
  assert.equal(cleared.deliveriesError, "");
  assert.equal(cleared.queueFailure, false);
});

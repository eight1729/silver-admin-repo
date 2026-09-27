import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createDeliveryRefresh, DELIVERY_REFRESH_MS, needsDeliveryRefresh } from "./delivery-refresh.ts";
import { sendThenLoadDeliveries } from "./admin-workflow.ts";
import type { AdminOperation, AdminDeliveries, DeliveryStatus } from "../lib/admin-api";

const operation = (status = "sending", id = "op-1") => ({ operation_id: id, status, send_requested_at: "requested" }) as AdminOperation;
const deliveries = (...statuses: DeliveryStatus[]) => ({ items: statuses.map((status) => ({ status })), summary: {} }) as AdminDeliveries;
function harness() {
  const timers = new Map<number, () => void>();
  let sequence = 0;
  let nextOperation = operation();
  let nextDeliveries = deliveries("pending");
  let failure = "";
  const calls: string[] = [];
  const updates: unknown[] = [];
  const errors: string[] = [];
  const loop = createDeliveryRefresh({
    operation: operation(), deliveries: deliveries("pending"),
    getOperation: async (id) => { calls.push(`operation:${id}`); if (failure === "operation") throw Error(); return nextOperation; },
    getDeliveries: async (id) => { calls.push(`deliveries:${id}`); if (failure === "deliveries") throw Error(); return nextDeliveries; },
    onUpdate: (op, result) => updates.push([op, result]), onError: () => { errors.push("error"); },
    schedule: (callback, delay) => { assert.equal(delay, DELIVERY_REFRESH_MS); timers.set(++sequence, callback); return sequence as unknown as ReturnType<typeof setTimeout>; },
    cancel: (id) => { timers.delete(id as unknown as number); },
  });
  return { loop, timers, calls, updates, errors,
    set: (op: AdminOperation, result: AdminDeliveries) => { nextOperation = op; nextDeliveries = result; },
    fail: (endpoint: string) => { failure = endpoint; },
    tick: async () => { const [id, callback] = timers.entries().next().value!; timers.delete(id); callback(); for (let i = 0; i < 6; i++) await Promise.resolve(); },
  };
}

for (const status of ["sent", "failed", "unknown", "skipped"] as const) {
  test(`pending -> ${status}: canonical pair is published and timer stops`, async () => {
    const h = harness();
    const op = operation(status === "sent" || status === "skipped" ? "completed" : "completed_with_errors");
    const result = deliveries(status);
    h.set(op, result); await h.tick();
    assert.deepEqual(h.updates, [[op, result]]);
    assert.deepEqual(h.calls, ["operation:op-1", "deliveries:op-1"]);
    assert.equal(h.timers.size, 0);
  });
}
test("pending and mixed states keep exactly one timer and use only GET dependencies", async () => {
  const h = harness();
  h.set(operation(), deliveries("sent", "pending"));
  await h.tick(); await h.tick();
  assert.equal(h.timers.size, 1); assert.equal(h.updates.length, 2);
  assert.equal(h.calls.length, 4); h.loop.stop();
});

test("three-recipient mixed results poll until canonical terminal aggregation", async () => {
  const h = harness();
  h.set(operation(), deliveries("sent", "pending", "pending"));
  await h.tick();
  assert.equal(h.timers.size, 1);
  h.set(operation("completed_with_errors"), deliveries("sent", "failed", "sent"));
  await h.tick();
  assert.equal(h.timers.size, 0);
  assert.equal(h.calls.length, 4);
});
test("unmount clears timer and prevents all later requests", async () => {
  const h = harness(); h.loop.stop(); await h.loop.refresh();
  assert.equal(h.timers.size, 0); assert.deepEqual(h.calls, []);
});
for (const endpoint of ["operation", "deliveries"]) {
  test(`${endpoint} GET failure retains previous snapshots and continues polling`, async () => {
    const h = harness(); h.fail(endpoint); await h.tick();
    assert.deepEqual(h.updates, []); assert.equal(h.errors.length, 1); assert.equal(h.timers.size, 1);
    h.fail(""); await h.loop.refresh();
    assert.equal(h.updates.length, 1); assert.equal(h.timers.size, 1); h.loop.stop();
  });
}
test("concurrent manual refreshes share the in-flight guard and replace scheduled timer", async () => {
  const h = harness();
  await Promise.all([h.loop.refresh(), h.loop.refresh(), h.loop.refresh()]);
  assert.equal(h.calls.length, 2); assert.equal(h.updates.length, 1); assert.equal(h.timers.size, 1);
  h.loop.stop();
});
test("operation switch aborts old request and suppresses stale completion", async () => {
  let resolve!: (op: AdminOperation) => void;
  let oldSignal!: AbortSignal;
  let oldUpdates = 0; let oldDeliveryCalls = 0;
  const old = createDeliveryRefresh({ operation: operation(), deliveries: deliveries("pending"),
    getOperation: (_id, signal) => { oldSignal = signal; return new Promise((r) => { resolve = r; }); },
    getDeliveries: async () => { oldDeliveryCalls++; return deliveries("sent"); },
    onUpdate: () => { oldUpdates++; }, onError: () => { throw Error("stale error"); },
  });
  const pending = old.refresh(); old.stop();
  const ids: string[] = [];
  const next = createDeliveryRefresh({ operation: operation("sending", "op-2"), deliveries: null,
    getOperation: async (id) => { ids.push(id); return operation("completed", id); },
    getDeliveries: async (id) => { ids.push(id); return deliveries("sent"); },
    onUpdate: () => {}, onError: () => { throw Error("unexpected"); },
  });
  await next.refresh(); resolve(operation("completed")); await pending;
  assert.equal(oldSignal.aborted, true); assert.equal(oldUpdates, 0); assert.equal(oldDeliveryCalls, 0);
  assert.deepEqual(ids, ["op-2", "op-2"]); next.stop();
});
test("stop during Delivery request suppresses stale state publication", async () => {
  let resolve!: (result: AdminDeliveries) => void;
  let updates = 0;
  const loop = createDeliveryRefresh({ operation: operation(), deliveries: null,
    getOperation: async () => operation("completed"),
    getDeliveries: () => new Promise((r) => { resolve = r; }),
    onUpdate: () => { updates++; }, onError: () => { throw Error(); },
  });
  const pending = loop.refresh(); await Promise.resolve(); loop.stop();
  resolve(deliveries("sent")); await pending; assert.equal(updates, 0);
});
test("terminal rules retain pending mixed results and wait for Operation convergence", () => {
  assert.equal(needsDeliveryRefresh(operation("completed"), deliveries("sent")), false);
  assert.equal(needsDeliveryRefresh(operation("completed_with_errors"), deliveries("unknown", "failed", "skipped")), false);
  assert.equal(needsDeliveryRefresh(operation("completed"), deliveries("sent", "pending")), true);
  assert.equal(needsDeliveryRefresh(operation(), deliveries("sent")), true);
  assert.equal(needsDeliveryRefresh(operation("completed"), null), true);
  assert.equal(needsDeliveryRefresh(operation("cancelled"), deliveries("pending")), false);
  assert.equal(needsDeliveryRefresh({ ...operation("ready"), send_requested_at: null }, null), false);
});
test("page shares GET-only refresh with retry and cleans up by operation identity", async () => {
  const source = await readFile(new URL("./page.tsx", import.meta.url), "utf8");
  const effect = source.slice(source.indexOf("const refreshOperationId"), source.indexOf("}, [refreshOperationId, refreshEnabled]);") + "}, [refreshOperationId, refreshEnabled]);".length);
  assert.match(effect, /getOperation: adminApi.operation, getDeliveries: adminApi.deliveries/);
  assert.match(effect, /refresh.stop\(\)/);
  assert.match(effect, /\[refreshOperationId, refreshEnabled\]/);
  assert.match(effect, /!restoringOperation/);
  assert.match(effect, /setOperation\(nextOperation\); setDeliveries\(nextDeliveries\)/);
  assert.doesNotMatch(effect, /adminApi.send/);
  assert.match(source, /await deliveryRefresh.current\?\.refresh\(\)/);
  assert.match(source, /currentDeliveries.items.every/);
});

test("send workflow plus automatic and manual refresh executes send exactly once", async () => {
  let sends = 0;
  let shownOperation = operation();
  let shownDeliveries = deliveries("pending");
  const initial = await sendThenLoadDeliveries({ operationId: "op-1",
    send: async () => { sends++; return shownOperation; },
    loadDeliveries: async () => shownDeliveries,
    onSent: (op) => { shownOperation = op; },
  });
  let callback: (() => void) | undefined;
  let status: DeliveryStatus = "pending";
  const loop = createDeliveryRefresh({ operation: initial.operation, deliveries: initial.deliveries,
    getOperation: async () => operation(status === "pending" ? "sending" : "completed"),
    getDeliveries: async () => deliveries(status),
    onUpdate: (op, result) => { shownOperation = op; shownDeliveries = result; },
    onError: () => { throw Error(); },
    schedule: (next) => { callback = next; return 1 as unknown as ReturnType<typeof setTimeout>; },
    cancel: () => { callback = undefined; },
  });
  callback!(); for (let i = 0; i < 6; i++) await Promise.resolve();
  assert.equal(shownOperation.status, "sending");
  status = "sent"; await loop.refresh();
  assert.equal(shownOperation.status, "completed");
  assert.equal(shownDeliveries.items[0].status, "sent");
  assert.equal(callback, undefined); assert.equal(sends, 1); loop.stop();
});

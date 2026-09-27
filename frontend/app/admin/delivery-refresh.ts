import type { AdminDeliveries, AdminOperation } from "../lib/admin-api";

export const DELIVERY_REFRESH_MS = 5000;

export function needsDeliveryRefresh(operation: AdminOperation, deliveries: AdminDeliveries | null): boolean {
  if (operation.status === "cancelled") return false;
  if (deliveries?.items.some((item) => item.status === "pending")) return true;
  if (operation.status === "completed" || operation.status === "completed_with_errors") return deliveries === null;
  return operation.status === "sending" || Boolean(operation.send_requested_at);
}

/** One GET-only refresh loop for one mounted operation. */
export function createDeliveryRefresh(args: {
  operation: AdminOperation;
  deliveries: AdminDeliveries | null;
  getOperation: (id: string, signal: AbortSignal) => Promise<AdminOperation>;
  getDeliveries: (id: string, signal: AbortSignal) => Promise<AdminDeliveries>;
  onUpdate: (operation: AdminOperation, deliveries: AdminDeliveries) => void;
  onError: () => void;
  schedule?: (callback: () => void, delay: number) => ReturnType<typeof setTimeout>;
  cancel?: (timer: ReturnType<typeof setTimeout>) => void;
}) {
  const schedule = args.schedule ?? setTimeout;
  const cancel = args.cancel ?? clearTimeout;
  const controller = new AbortController();
  let operation = args.operation;
  let deliveries = args.deliveries;
  let stopped = false;
  let inFlight = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const clear = () => { if (timer !== undefined) cancel(timer); timer = undefined; };
  const queue = () => {
    if (!stopped && timer === undefined && needsDeliveryRefresh(operation, deliveries)) {
      timer = schedule(() => { timer = undefined; void refresh(); }, DELIVERY_REFRESH_MS);
    }
  };
  async function refresh() {
    if (stopped || inFlight) return;
    clear();
    inFlight = true;
    try {
      // Sequential requests cannot leave another GET running when one fails.
      const nextOperation = await args.getOperation(args.operation.operation_id, controller.signal);
      if (stopped) return;
      const nextDeliveries = await args.getDeliveries(args.operation.operation_id, controller.signal);
      if (stopped) return;
      if (nextOperation.operation_id !== args.operation.operation_id) throw new Error("Operation identity mismatch");
      operation = nextOperation; deliveries = nextDeliveries;
      args.onUpdate(operation, deliveries);
    } catch {
      if (!stopped) args.onError();
    } finally {
      inFlight = false;
      queue();
    }
  }
  queue();
  return { refresh, stop: () => { stopped = true; clear(); controller.abort(); } };
}

import type { AdminCandidate, AdminDeliveries, AdminJobDetail, AdminMessage, AdminOperation, AdminValidation, NotificationType } from "../lib/admin-api";

type CreateBody = AdminMessage & { job_id: string; notification_type: NotificationType };

export async function createOrSaveTargets(args: {
  operation: AdminOperation | null; jobId: string; createBody: CreateBody; selectedMemberIds: string[];
  create: (body: CreateBody) => Promise<AdminOperation>;
  saveTargets: (operationId: string, ids: string[]) => Promise<AdminOperation>;
  reload: (operationId: string) => Promise<AdminOperation>;
  onCreated: (operation: AdminOperation) => void;
}): Promise<AdminOperation> {
  let operation = args.operation;
  if (!operation || operation.job_id !== args.jobId) {
    operation = await args.create(args.createBody);
    args.onCreated(operation);
  }
  await args.saveTargets(operation.operation_id, [...new Set(args.selectedMemberIds)]);
  return args.reload(operation.operation_id);
}

export async function saveThenValidate(args: {
  operationId: string; message: AdminMessage;
  save: (id: string, message: AdminMessage) => Promise<AdminOperation>;
  validate: (id: string) => Promise<AdminValidation>;
}): Promise<{ operation: AdminOperation; validation: AdminValidation }> {
  const operation = await args.save(args.operationId, args.message);
  const validation = await args.validate(args.operationId);
  return { operation, validation };
}

export async function sendThenLoadDeliveries(args: {
  operationId: string;
  send: (id: string) => Promise<AdminOperation>;
  loadDeliveries: (id: string) => Promise<AdminDeliveries>;
  onSent: (operation: AdminOperation) => void;
}): Promise<{ operation: AdminOperation; deliveries: AdminDeliveries | null; deliveryError: unknown | null }> {
  const operation = await args.send(args.operationId);
  args.onSent(operation);
  try { return { operation, deliveries: await args.loadDeliveries(args.operationId), deliveryError: null }; }
  catch (deliveryError) { return { operation, deliveries: null, deliveryError }; }
}

export async function reloadDeliveryResults(args: {
  operation: AdminOperation;
  actions: {
    sendOperation: (id: string) => Promise<AdminOperation>;
    getDeliveries: (id: string) => Promise<AdminDeliveries>;
  };
}): Promise<{ operation: AdminOperation; deliveries: AdminDeliveries | null; deliveryError: unknown | null }> {
  try {
    return { operation: args.operation, deliveries: await args.actions.getDeliveries(args.operation.operation_id), deliveryError: null };
  } catch (deliveryError) {
    return { operation: args.operation, deliveries: null, deliveryError };
  }
}

export async function restoreAdminOperation(args: {
  operationId: string;
  getOperation: (id: string) => Promise<AdminOperation>;
  onOperationRestored: (operation: AdminOperation, step: "edit" | "result") => void;
  getJob: (id: string) => Promise<AdminJobDetail>;
  getCandidates: (id: string) => Promise<AdminCandidate[]>;
  deliveryActions: {
    sendOperation: (id: string) => Promise<AdminOperation>;
    getDeliveries: (id: string) => Promise<AdminDeliveries>;
  };
  isNotFound: (error: unknown) => boolean;
  removeStoredOperationId: () => void;
}): Promise<{
  operation: AdminOperation | null;
  operationError: unknown | null;
  job: AdminJobDetail | null;
  jobError: unknown | null;
  candidates: AdminCandidate[];
  candidatesError: unknown | null;
  deliveries: AdminDeliveries | null;
  deliveryError: unknown | null;
}> {
  let operation: AdminOperation;
  try { operation = await args.getOperation(args.operationId); }
  catch (operationError) {
    if (args.isNotFound(operationError)) args.removeStoredOperationId();
    return { operation: null, operationError, job: null, jobError: null, candidates: [], candidatesError: null, deliveries: null, deliveryError: null };
  }
  const step = operation.status === "completed" || operation.status === "completed_with_errors" ? "result" : "edit";
  args.onOperationRestored(operation, step);
  const jobRequest = args.getJob(operation.job_id);
  const candidatesRequest = args.getCandidates(operation.job_id);
  const deliveryRequest = step === "result"
    ? reloadDeliveryResults({ operation, actions: args.deliveryActions })
    : Promise.resolve({ operation, deliveries: null, deliveryError: null });
  const [[jobResult, candidatesResult], deliveryResult] = await Promise.all([
    Promise.allSettled([jobRequest, candidatesRequest]), deliveryRequest,
  ]);
  return {
    operation, operationError: null,
    job: jobResult.status === "fulfilled" ? jobResult.value : null,
    jobError: jobResult.status === "rejected" ? jobResult.reason : null,
    candidates: candidatesResult.status === "fulfilled" ? candidatesResult.value : [],
    candidatesError: candidatesResult.status === "rejected" ? candidatesResult.reason : null,
    deliveries: deliveryResult.deliveries, deliveryError: deliveryResult.deliveryError,
  };
}

export function clearedTransientAdminState() {
  return {
    selectedJobId: null, targetsPending: false, validation: null, deliveries: null,
    detailError: false, candidatesError: false, deliveriesError: "", queueFailure: false,
  } as const;
}

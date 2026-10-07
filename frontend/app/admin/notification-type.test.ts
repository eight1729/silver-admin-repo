import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import test from "node:test";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createOrSaveTargets, restoreAdminOperation } from "./admin-workflow.ts";
import type { AdminOperation, NotificationType } from "../lib/admin-api.ts";
import { toggleCandidateSelection } from "./candidate-selection.ts";

const require = createRequire(import.meta.url);
const root = dirname(fileURLToPath(import.meta.url));
const page = readFileSync(resolve(root, "page.tsx"), "utf8");
const types: NotificationType[] = ["new_job_match", "existing_job_match", "custom_job"];
let candidatePage = 1;
// Execute actual TSX with inert hooks; no Next server, env files, or network.
function load(path: string): Record<string, unknown> {
  const code = ts.transpileModule(readFileSync(path, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020,
  } }).outputText;
  const module = { exports: {} };
  runInNewContext(code, { module, exports: module.exports, require: (id: string) => {
    if (id === "react") return { ...React, useState: (value: unknown) => [typeof value === "number" ? candidatePage : value, () => {}], useEffect: () => {} };
    if (!id.startsWith(".")) return require(id);
    const base = resolve(dirname(path), id);
    return load(existsSync(base + ".ts") ? base + ".ts" : base + ".tsx");
  } });
  return module.exports;
}
const panels = load(resolve(root, "MajorPanels.tsx"));
type Element = React.ReactElement<{ children?: React.ReactNode; value?: string; disabled?: boolean; onChange?: (event: { target: { value: string } }) => void }>;
function findSelect(node: React.ReactNode): Element | undefined {
  for (const child of React.Children.toArray(node)) {
    if (!React.isValidElement(child)) continue;
    const element = child as Element;
    if (element.type === "select") return element;
    const found = findSelect(element.props.children);
    if (found) return found;
  }
}
function panel(value: NotificationType, locked: boolean, busy = false) {
  const changes: string[] = [];
  assert.equal(typeof panels.CandidateSelectionPanel, "function");
  const Component = panels.CandidateSelectionPanel as (props: Record<string, unknown>) => React.ReactNode;
  const tree = Component({ job: { job_id: "job-1", status: "published" }, candidates: [], selected: new Set(),
    notificationType: value, notificationTypeLocked: locked, busy, editable: true, filter: "all",
    setNotificationType: (next: string) => changes.push(next), setFilter: () => {},
  });
  const select = findSelect(tree);
  assert.ok(select);
  return { select, changes, html: renderToStaticMarkup(tree) };
}
function operation(type: NotificationType): AdminOperation {
  return { operation_id: "op-1", job_id: "job-1", job_version: "v1", notification_type: type,
    message: { greeting: "hello", introduction: "body", note: "note" }, status: "draft",
    target_count: 0, selected_count: 0, validated_at: null, send_requested_at: null, completed_at: null,
    created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z" };
}

for (const type of types) {
  test(`${type}: pre-create select enabled, canonical choices, selected type sent to create`, async () => {
    const ui = panel(type, false);
    assert.equal(ui.select.props.disabled, false);
    const options = React.Children.toArray(ui.select.props.children) as Element[];
    assert.deepEqual(options.map(option => option.props.value), types);
    ui.select.props.onChange!({ target: { value: type } });
    assert.deepEqual(ui.changes, [type]);
    let created = false;
    const saved = operation(type);
    await createOrSaveTargets({ operation: null, jobId: saved.job_id,
      createBody: { job_id: saved.job_id, notification_type: type, ...saved.message }, selectedMemberIds: ["M1"],
      create: async body => { assert.equal(body.notification_type, type); created = true; return saved; },
      onCreated: op => assert.equal(op.notification_type, type), saveTargets: async () => saved, reload: async () => saved,
    });
    assert.equal(created, true);
  });
  test(`${type}: saved select is locked and target retry retains persisted type`, async () => {
    const ui = panel(type, true);
    assert.equal(ui.select.props.disabled, true);
    assert.equal(ui.select.props.value, type);
    assert.match(ui.html, new RegExp(`value="${type}" selected=""`));
    ui.select.props.onChange!({ target: { value: "custom_job" } });
    assert.deepEqual(ui.changes, []);
    const saved = operation(type);
    const result = await createOrSaveTargets({ operation: saved, jobId: saved.job_id,
      createBody: { job_id: saved.job_id, notification_type: "custom_job", ...saved.message }, selectedMemberIds: ["M1"],
      create: async () => { throw new Error("existing Operation must not be recreated"); },
      onCreated: () => assert.fail("must reuse"), saveTargets: async () => saved, reload: async () => saved,
    });
    assert.equal(result.notification_type, type);
  });
  test(`${type}: restore fetches persisted type instead of default`, async () => {
    const saved = operation(type);
    let restored: NotificationType | null = null;
    await restoreAdminOperation({ operationId: saved.operation_id, getOperation: async () => saved,
      onOperationRestored: op => { restored = op.notification_type; },
      getJob: async () => { throw new Error("irrelevant detail unavailable"); }, getCandidates: async () => [],
      deliveryActions: { sendOperation: async () => assert.fail("restore never sends"), getDeliveries: async () => assert.fail("draft") },
      isNotFound: () => false, removeStoredOperationId: () => assert.fail("keep stored id"),
    });
    assert.equal(restored, type);
    assert.equal(panel(restored!, true).select.props.value, type);
  });
}

test("page handler blocks internal changes after creation and during create, then permits reset", () => {
  const handler = page.slice(page.indexOf("  function changeNotificationType("), page.indexOf("  function changeMessage("));
  const code = ts.transpileModule(handler, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText;
  for (const [saved, busy, expected] of [[operation("existing_job_match"), false, 0], [null, true, 0], [null, false, 1]] as const) {
    let changes = 0;
    runInNewContext(code + '\nchangeNotificationType("custom_job");', {
      operation: saved, busy, notificationType: "new_job_match", validation: null, validationSnapshot: null,
      setNotificationType: () => { changes++; }, setValidationSnapshot: () => {}, setDeliveries: () => {}, setDeliveriesError: () => {},
    });
    assert.equal(changes, expected);
  }
  const reset = page.slice(page.indexOf("  function resetCurrentNotificationContext()"), page.indexOf("  function requestJobSelection("));
  assert.match(reset, /setOperation\(null\)/);
  assert.match(reset, /sessionStorage\.removeItem\(STORAGE_KEY\)/);
  assert.equal(panel("existing_job_match", false).select.props.disabled, false);
  assert.equal(panel("new_job_match", false, true).select.props.disabled, true);
});

test("page wiring always prefers persisted type across workflow steps and restores local draft", () => {
  assert.match(page, /notificationType=\{operation\?\.notification_type \?\? notificationType\} notificationTypeLocked=\{operation !== null\}/);
  assert.match(page, /setOperation\(op\); setMessage\(op\.message\); setNotificationType\(op\.notification_type\)/);
  assert.match(page, /notification_type: notificationType/);
  assert.match(page, /sessionStorage\.getItem\(STORAGE_KEY\)/);
});

test("candidate checkboxes preserve multiple selection across pages and filters and enforce finite limits", () => {
  const Component = panels.CandidateSelectionPanel as (props: Record<string, unknown>) => React.ReactNode;
  let selected = new Set<string>();
  let maxRecipients: number | null = null;
  const candidates = Array.from({ length: 7 }, (_, index) => ({ member_id: `M${index}`, display_name: `Member ${index}`,
    eligible: true, line_linked: index !== 0, preference_summary: "" }));
  function inputs(node: React.ReactNode): React.ReactElement<Record<string, unknown>>[] {
    return React.Children.toArray(node).flatMap(child => {
      if (!React.isValidElement(child)) return [];
      const element = child as React.ReactElement<Record<string, unknown>>;
      return element.type === "input" ? [element] : inputs(element.props.children as React.ReactNode);
    });
  }
  function render(filter = "all", editable = true) {
    return Component({ job: { job_id: "job", status: "published" }, candidates, selected, maxRecipients,
      notificationType: "custom_job", notificationTypeLocked: true, busy: false, editable, filter,
      setFilter: () => {}, toggle: (id: string) => { selected = toggleCandidateSelection(selected, id, maxRecipients); } });
  }
  function click(index: number) {
    const input = inputs(render())[index];
    assert.equal(input.props.type, "checkbox");
    assert.ok(input.props["aria-label"]);
    (input.props.onChange as () => void)();
  }
  try {
    candidatePage = 1;
    click(0); click(1); click(2); click(1);
    assert.deepEqual([...selected], ["M0", "M2"]);
    assert.equal(inputs(render())[0].props.checked, true);
    candidatePage = 2; click(0);
    assert.deepEqual([...selected], ["M0", "M2", "M5"]);
    candidatePage = 1;
    assert.match(renderToStaticMarkup(render("line_linked")), /選択中の会員は現在の絞り込み結果には表示されていません/);
    assert.deepEqual([...selected], ["M0", "M2", "M5"]);
    maxRecipients = 1; selected = new Set(["M0"]);
    assert.equal(inputs(render())[1].props.disabled, true);
    click(1); assert.deepEqual([...selected], ["M0"]);
    click(0); click(1); assert.deepEqual([...selected], ["M1"]);
    assert.match(renderToStaticMarkup(render()), /実LINE検証では1名だけ/);
    maxRecipients = null;
    assert.doesNotMatch(renderToStaticMarkup(render()), /実LINE検証では1名だけ/);
    assert.equal(inputs(render("all", false))[1].props.disabled, true);
  } finally { candidatePage = 1; }
});


test("member number is display-only; checkbox selection keeps UUID with null/absent fallback", () => {
  const Component = panels.CandidateSelectionPanel as (props: Record<string, unknown>) => React.ReactNode;
  const id = "144813ad-bed4-4330-b592-0e6aebcfd1bc";
  for (const number of ["0001", null, undefined]) {
    const selected: string[] = [];
    const tree = Component({ job: { job_id: "job-1", status: "published" },
      candidates: [{ member_id: id, member_number: number, display_name: "Member", eligible: true, line_linked: true }],
      selected: new Set(), editable: true, busy: false, filter: "all", notificationType: "new_job_match",
      toggle: (value: string) => selected.push(value), setFilter: () => {}, setNotificationType: () => {},
    });
    assert.ok(renderToStaticMarkup(tree).includes(`<th scope="row">${number ?? id}</th>`));
    function visit(node: React.ReactNode) {
      React.Children.forEach(node, child => {
        if (!React.isValidElement(child)) return;
        const element = child as React.ReactElement<any>;
        if (element.type === "input" && element.props.name === "admin-selected-candidate") element.props.onChange();
        visit(element.props.children);
      });
    }
    visit(tree);
    assert.deepEqual(selected, [id]);
  }
});


test("candidate panel renders member number order before pagination and selects the original UUID", () => {
  const Component = panels.CandidateSelectionPanel as (props: Record<string, unknown>) => React.ReactNode;
  const selected: string[] = [];
  const candidates = ["0003", "0001", "0002", "0010"].map(number => ({
    member_id: `uuid-${number}`, member_number: number, display_name: "Member", eligible: true, line_linked: true,
  }));
  const tree = Component({ job: { job_id: "job-1", status: "published" }, candidates,
    selected: new Set(), editable: true, busy: false, filter: "all", notificationType: "new_job_match",
    toggle: (value: string) => selected.push(value), setFilter: () => {}, setNotificationType: () => {},
  });
  const html = renderToStaticMarkup(tree);
  const positions = ["0001", "0002", "0003", "0010"].map(n => html.indexOf(`<th scope="row">${n}</th>`));
  assert.ok(positions.every((p, index) => p >= 0 && (index === 0 || p > positions[index - 1])));
  function visit(node: React.ReactNode) {
    React.Children.forEach(node, child => {
      if (!React.isValidElement(child)) return;
      const element = child as React.ReactElement<any>;
      if (element.type === "input" && element.props.name === "admin-selected-candidate") element.props.onChange();
      visit(element.props.children);
    });
  }
  visit(tree);
  assert.deepEqual(selected, ["uuid-0001", "uuid-0002", "uuid-0003", "uuid-0010"]);
  assert.equal(candidates[0].member_number, "0003");
});

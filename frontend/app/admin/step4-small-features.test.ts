import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import type { AdminCandidate } from "../lib/admin-api.ts";
import { candidateFilters, filterCandidates } from "./candidate-filters.ts";
import { composeAdminMessage, createTemplateMessage, notificationBody, notificationDisplayText, notificationNotice, notificationTemplates, replaceExactCenterName, replaceExactNotice } from "./notification-templates.ts";

const job = { title: "清掃業務", description: "公園内の清掃", workTime: "8:00〜12:00", workDays: "週3日", summary: "屋外での軽作業" };

test("five notification templates generate only the contracted display text", () => {
  assert.deepEqual(notificationTemplates.map((template) => template.id), ["standard", "urgent", "reminder", "personal", "blank"]);
  const standard = createTemplateMessage("standard", "表示センター", job, "登録状況をご確認ください。");
  assert.match(notificationBody(standard), /^【清掃業務の求人お知らせについて】/);
  for (const text of ["表示センターです。", "就業内容）公園内の清掃", "勤務時間）8:00〜12:00", "勤務日）週3日", "概要）屋外での軽作業", "登録状況をご確認ください。", "その他のお仕事はLINEミニアプリからご確認ください。"]) assert.match(notificationBody(standard), new RegExp(text));
  assert.equal(notificationNotice(standard), "登録状況をご確認ください。");
  assert.equal(notificationDisplayText(standard), notificationBody(standard), "notice embedded in the body must not be duplicated");
  assert.doesNotMatch(notificationBody(standard), /https?:\/\/|liff\.line\.me/);
  assert.ok(standard.introduction.length > 0, "the unchanged API contract requires three non-empty saved fields");
  assert.match(notificationBody(createTemplateMessage("urgent", "表示センター", job)), /^【急募：清掃業務】/);
  assert.match(notificationBody(createTemplateMessage("reminder", "表示センター", job)), /^【再案内：清掃業務】/);
  assert.match(notificationBody(createTemplateMessage("personal", "表示センター", job)), /^【個別案内：清掃業務】/);
  assert.equal(notificationBody(createTemplateMessage("blank", "表示センター", job)), "");
});

test("single editor body round-trips through the unchanged three-field API contract", () => {
  const message = composeAdminMessage("全文をそのまま編集", "注意事項");
  assert.equal(notificationBody(message), "全文をそのまま編集");
  assert.equal(notificationDisplayText(message), "全文をそのまま編集\n\n注意事項");
  assert.equal(message.note, "注意事項");
});

test("missing template values never expose placeholders or nullish text", () => {
  const rendered = Object.values(createTemplateMessage("standard", "", { title: "", description: null, workTime: undefined, workDays: null, summary: undefined })).join("\n");
  assert.doesNotMatch(rendered, /undefined|null|{{center_name}}|{{job_name}}/);
  assert.doesNotMatch(rendered, /就業内容）|勤務時間）|勤務日）|概要）/);
  assert.doesNotMatch(rendered, /member|subject|operation|service/i);
});

test("notice replacement is exact, idempotent, and never duplicates the notice", () => {
  const source = createTemplateMessage("standard", "表示センター", job, "旧注意");
  const replaced = replaceExactNotice(source, "旧注意", "新注意");
  assert.equal(notificationNotice(replaced), "新注意");
  assert.equal((notificationBody(replaced).match(/新注意/g) ?? []).length, 1);
  assert.equal(notificationBody(replaceExactNotice(replaced, "新注意", "新注意")), notificationBody(replaced));
});

test("center replacement changes exact text only and does not mutate its input", () => {
  const source = { greeting: "旧センターです。", introduction: "旧センターとは別の文章", note: "旧 センター" };
  const replaced = replaceExactCenterName(source, "旧センター", "新センター");
  assert.deepEqual(replaced, { greeting: "新センターです。", introduction: "新センターとは別の文章", note: "旧 センター" });
  assert.equal(source.greeting, "旧センターです。");
});

const candidates: AdminCandidate[] = [
  { member_id: "M1", display_name: "会員A", line_linked: true, eligible: true, reason: null, selected: false },
  { member_id: "M2", display_name: "会員B", line_linked: false, eligible: true, reason: null, selected: false },
  { member_id: "M3", display_name: "会員C", line_linked: true, eligible: false, reason: "member_ineligible", selected: false },
];

test("candidate filters use only API attributes and preserve source order and data", () => {
  const original = structuredClone(candidates);
  assert.deepEqual(candidateFilters.map((filter) => filter.id), ["all", "line_linked", "eligible"]);
  assert.deepEqual(filterCandidates(candidates, "all").map((item) => item.member_id), ["M1", "M2", "M3"]);
  assert.deepEqual(filterCandidates(candidates, "line_linked").map((item) => item.member_id), ["M1", "M3"]);
  assert.deepEqual(filterCandidates(candidates, "eligible").map((item) => item.member_id), ["M1", "M2"]);
  assert.deepEqual(candidates, original);
  assert.notEqual(filterCandidates(candidates, "all"), candidates);
});

test("UI keeps filtering separate from selection and validation state", async () => {
  const panels = await readFile(new URL("./MajorPanels.tsx", import.meta.url), "utf8");
  const page = await readFile(new URL("./page.tsx", import.meta.url), "utf8");
  assert.match(panels, /filterCandidates\(candidates, filter\)/);
  assert.match(panels, /selected\.has\(candidate\.member_id\)/);
  assert.match(panels, /選択中の会員は現在の絞り込み結果には表示されていません/);
  assert.match(page, /useState<CandidateFilterId>\("all"\)/);
  assert.match(page, /CandidateFilterMenu value=\{candidateFilter\} onChange=\{setCandidateFilter\}/);
  assert.match(panels, /useEffect\(\(\) => setPage\(1\), \[filter\]\)/);
  assert.doesNotMatch(page, /setValidationInvalidation\([^)]*filter/i);
  assert.match(page, /通知テンプレートを変更しますか？/);
  assert.match(page, /現在の通知本文は、選択したテンプレートの内容で置き換えられます/);
  assert.doesNotMatch(page, /window\.confirm/);
  assert.match(page, /function applyEditorFields\(\)/);
  assert.match(page, /replaceExactCenterName\(nextMessage, centerDisplayName, nextName\)/);
  assert.match(page, /replaceExactNotice\(nextMessage, appliedNotice, nextNotice\)/);
  assert.match(page, /changeMessageFromTool\(nextMessage, "センター名または注意事項が本文へ反映されたため/);
  assert.doesNotMatch(page, /localStorage|recommendationScore|recommendationRank/);
});

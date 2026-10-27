import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import type { AdminCandidate } from "../lib/admin-api.ts";
import { candidateFilters, filterCandidates } from "./candidate-filters.ts";
import { composeAdminMessage, hasUnfilledNotificationFields, createTemplateMessage, notificationBody, notificationDisplayText, notificationNotice, notificationTemplates, replaceExactCenterName, replaceExactNotice } from "./notification-templates.ts";

const job = { title: "清掃業務", description: "公園内の清掃", location: "公園", workTime: "8:00〜12:00", workDays: "週3日", summary: "屋外での軽作業" };

test("five notification templates generate only the contracted display text", () => {
  assert.deepEqual(notificationTemplates.map((template) => template.id), ["standard", "urgent", "reminder", "personal", "blank"]);
  const standard = createTemplateMessage("standard", "表示センター", job, "登録状況をご確認ください。");
  assert.match(notificationBody(standard), /^■就業案内\n【お仕事のご案内】/);
  for (const text of ["表示センターです。", "◆ お仕事の内容\n　公園内の清掃", "◆ 時間\n　8:00〜12:00", "◆ 働く日\n　週3日", "◆ 働く場所\n　公園", "登録状況をご確認ください。", "その他の仕事は↓メニュー「求人中のお仕事」からご確認ください。"]) assert.match(notificationBody(standard), new RegExp(text));
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
  assert.match(panels, /filterCandidates\(orderCandidates\(candidates, selected\), filter, minimumMemberNumber\)/);
  assert.match(panels, /selected\.has\(candidate\.member_id\)/);
  assert.match(panels, /現在の絞り込み結果に表示されていない選択済み会員:/);
  assert.match(page, /useState<CandidateFilterId>\("all"\)/);
  assert.match(page, /CandidateFilterMenu value=\{candidateFilter\} onChange=\{setCandidateFilter\}/);
  assert.match(panels, /useEffect\(\(\) => setPage\(1\), \[filter, minimumMemberNumber\]\)/);
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


test("standard layout uses verified fields and leaves payment and headcount for staff", () => {
  const message = createTemplateMessage("standard", "墨田区シルバー人材センター", job);
  assert.equal(notificationBody(message), `■就業案内
【お仕事のご案内】
いつもお世話になっております。
墨田区シルバー人材センターです。
下記の求人をご案内します。

◆ お仕事の内容
　公園内の清掃

◆ 働く場所
　公園

◆ 働く日
　週3日

◆ 時間
　8:00〜12:00

◆ 配分金
　【未入力：配分金】

◆ 募集人数
　【未入力：募集人数】
━━━━━━━━━━━━
ご希望の方は、下の「電話する」ボタンからセンターへご連絡ください。

その他の仕事は↓メニュー「求人中のお仕事」からご確認ください。`);
  assert.equal(hasUnfilledNotificationFields(message), true);
  assert.equal(hasUnfilledNotificationFields({ ...message, greeting: message.greeting.replace("【未入力：配分金】", "1,200円/時間").replace("【未入力：募集人数】", "3名") }), false);
  const added = replaceExactNotice(message, "", "注意文");
  assert.equal(notificationNotice(added), "注意文");
  assert.deepEqual(replaceExactNotice(added, "注意文", ""), message);
});

test("automatic and manual template entry points carry location, days and time", async () => {
  for (const file of ["page.tsx", "AutomaticNotification.tsx"]) {
    const source = await readFile(new URL(file, import.meta.url), "utf8");
    assert.match(source, /createTemplateMessage\("standard"/);
    assert.match(source, /location: (?:currentJob|detail)\.location/);
    assert.match(source, /workDays: summary\?\.work_days/);
    assert.match(source, /workTime: summary\?\.work_time/);
    assert.doesNotMatch(source, /内容をご確認ください。/);
  }
});


test("unfilled checks reserve generated field lines without restricting custom prose or other templates", () => {
  for (const template of ["urgent", "reminder", "personal"] as const) {
    assert.equal(hasUnfilledNotificationFields(createTemplateMessage(template, "表示センター", job)), false);
  }
  assert.equal(hasUnfilledNotificationFields(createTemplateMessage("blank", "表示センター")), false);
  for (const text of ["自由編集", "【未入力：担当者】", "【未入力：配分金】という表示は入力欄の説明です。"])
    assert.equal(hasUnfilledNotificationFields(composeAdminMessage(text, "注意")), false);
  for (const field of ["センター名", "仕事内容", "働く場所", "働く日", "時間", "配分金", "募集人数"])
    assert.equal(hasUnfilledNotificationFields(composeAdminMessage(`本文\n　【未入力：${field}】\n`, "注意")), true);
  assert.equal(hasUnfilledNotificationFields(composeAdminMessage("【未入力：センター名】です。\r\n本文", "注意")), true);
});

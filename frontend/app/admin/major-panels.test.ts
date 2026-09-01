import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

async function source() {
  return readFile(new URL("./MajorPanels.tsx", import.meta.url), "utf8");
}

test("job selection uses a compact semantic single-select table", async () => {
  const text = await source();
  const jobPanel = text.slice(text.indexOf("export function JobSelectionPanel"), text.indexOf("export function CandidateSelectionPanel"));
  for (const field of ["title", "job_id", "status", "summary", "work_days", "work_time"]) assert.match(jobPanel, new RegExp(`item\\.${field}`));
  assert.match(jobPanel, /<table className="job-selection-table">/);
  assert.match(jobPanel, /<thead>/);
  assert.match(jobPanel, /<tbody>/);
  for (const heading of ["求人名", "勤務日", "勤務時間", "概要"]) assert.match(jobPanel, new RegExp(`<th scope="col">${heading}</th>`));
  assert.match(jobPanel, /type="radio"/);
  assert.match(jobPanel, /name="admin-selected-job"/);
  assert.match(jobPanel, /aria-label=\{`\$\{item\.title\}を選択`\}/);
  assert.match(jobPanel, /onClick=\{\(\) => \{ if \(!disabled && !selected\) void select\(item\.job_id\); \}\}/);
  assert.match(jobPanel, /href="\/admin\/jobs"/);
  assert.doesNotMatch(jobPanel, /表示求人数|現在の選択|求人ID:/);
  assert.match(jobPanel, /求人を読み込んでいます/);
  assert.match(jobPanel, /求人一覧を取得できませんでした/);
  assert.match(jobPanel, /現在選択できる求人はありません/);
  assert.match(jobPanel, /className=\{`\$\{selected \? "is-selected"/);
  const page = await readFile(new URL("./page.tsx", import.meta.url), "utf8");
  const panel = await readFile(new URL("./AdminPanel.tsx", import.meta.url), "utf8");
  const css = await readFile(new URL("./admin.css", import.meta.url), "utf8");
  assert.match(page, /title="求人選択" badge=\{`\$\{jobs\.length\}件`\}/);
  assert.match(panel, /admin-panel-count/);
  assert.match(css, /job-selection-table-wrapper\{max-height:220px;overflow:auto/);
  assert.match(css, /tbody tr\.is-selected\{background:#e8f6ef\}/);
});

test("staging candidate selection visibly enforces one recipient", async () => {
  const text = await source();
  const candidatePanel = text.slice(text.indexOf("export function CandidateSelectionPanel"), text.indexOf("export function MessageEditorPanel"));
  assert.match(text, /singleRecipient && selected\.size >= 1 && !isSelected/);
  assert.match(text, /singleRecipient && selected\.size !== 1/);
  assert.match(text, /実LINE検証では1名だけ選択できます/);
  assert.match(text, /連携済み/);
  assert.match(text, /通知可能/);
  assert.match(candidatePanel, /<table className="candidate-selection-table">/);
  for (const heading of ["会員ID", "氏名", "希望条件", "LINE連携", "通知可否"]) assert.match(candidatePanel, new RegExp(`<th scope="col">${heading}</th>`));
  assert.match(candidatePanel, /type="radio"/);
  assert.match(candidatePanel, /name="admin-selected-candidate"/);
  assert.match(candidatePanel, /candidate\.preference_summary/);
  assert.match(candidatePanel, /const pageSize = 5/);
  assert.match(candidatePanel, /visibleCandidates\.slice/);
  assert.match(candidatePanel, /setPage\(1\)/);
  assert.match(candidatePanel, /aria-current=\{pageNumber === currentPage \? "page" : undefined\}/);
  assert.match(candidatePanel, /href=\{`\/admin\/members\?jobId=/);
  assert.doesNotMatch(candidatePanel, /type="checkbox"|candidate-selection-list/);
  const page = await readFile(new URL("./page.tsx", import.meta.url), "utf8");
  assert.match(page, /title="対象候補会員" badge=\{job \? `\$\{job\.title\}・\$\{candidates\.length\}人`/);
  assert.doesNotMatch(text, /line_subject|allowlist|おすすめ順位|推薦点/);
});

test("candidate panel uses a compact accessible filter menu and footer controls", async () => {
  const text = await source();
  const filterMenu = text.slice(text.indexOf("export function CandidateFilterMenu"), text.indexOf("export function JobSelectionPanel"));
  const candidatePanel = text.slice(text.indexOf("export function CandidateSelectionPanel"), text.indexOf("export function MessageEditorPanel"));
  for (const contract of [/aria-expanded=\{open\}/, /aria-controls="candidate-filter-options"/, /role="menu"/, /role="menuitemradio"/, /aria-checked=/, /event\.key === "Escape"/, /document\.addEventListener\("mousedown"/]) assert.match(filterMenu, contract);
  assert.match(filterMenu, /条件で絞り込み/);
  assert.match(candidatePanel, /candidate-footer-actions/);
  assert.match(candidatePanel, /対象を保存して通知文編集へ/);
  assert.match(candidatePanel, /candidate-limit-note/);
  assert.doesNotMatch(candidatePanel, /candidate-filter-controls|candidate-filter-field/);
  const css = await readFile(new URL("./admin.css", import.meta.url), "utf8");
  assert.match(css, /candidate-selection-table\{width:100%;min-width:0;[^}]*table-layout:fixed/);
  assert.match(css, /candidate-table-wrapper\{overflow-x:visible/);
  assert.match(css, /@media\(max-width:760px\)[\s\S]*candidate-table-wrapper\{overflow-x:auto\}/);
});

test("message editor separates editable copy from system supplied fields", async () => {
  const text = await source();
  const editor = text.slice(text.indexOf("export function MessageEditorPanel"), text.indexOf("export function MessageReadOnlySummary"));
  assert.equal((editor.match(/<textarea/g) ?? []).length, 2, "one message body and one persisted note are editable");
  assert.match(editor, /id="notification-body"/);
  assert.match(editor, /id="notification-note"/);
  assert.match(editor, /notificationBody\(message\)/);
  assert.match(editor, /composeAdminMessage\(event\.target\.value, message\.note\)/);
  assert.match(editor, /aria-label="通知テンプレート"/);
  assert.match(editor, /センター名/);
  assert.match(editor, /readonly-canonical-url/);
  assert.match(editor, /システム付与:/);
  assert.match(editor, /aria-live="polite"/);
  assert.equal((editor.match(/本文へ反映/g) ?? []).length, 1);
  assert.match(editor, /value=\{noticeDraft\}/);
  assert.match(editor, /onClick=\{applyEditorFields\}/);
  assert.doesNotMatch(editor, /compact-input-action|applyCenterDisplayName/);
  assert.doesNotMatch(editor, /message-greeting|message-introduction|message-note|対象選択へ戻る|下書きを保存|保存して検証/);
  const page = await readFile(new URL("./page.tsx", import.meta.url), "utf8");
  assert.match(page, /title="通知文編集" badge=\{job\?\.title\}/);
  assert.match(page, /<SendPreparationState[^>]*save=\{saveMessage\}[^>]*validate=\{validate\}/);
  assert.match(text, /下書き保存/);
  assert.match(text, /: "検証"/);
  assert.match(text, /送信実行/);
  assert.match(text, />通知文編集<\/button>/);
  assert.match(text, /message-readonly-actions/);
  assert.match(text, /求人リンクを準備しています/);
  const css = await readFile(new URL("./admin.css", import.meta.url), "utf8");
  assert.match(css, /editor-reflect-actions\{display:flex;justify-content:flex-end/);
  assert.doesNotMatch(css, /editor-reflect-actions[^}]*position:absolute/);
});

test("send confirmation is a compact four-row summary with conditional safe details", async () => {
  const text = await source();
  const headings = ["対象会員数", "LINE未連携数", "送信対象会員数", "検証結果"];
  let previous = -1;
  for (const heading of headings) {
    const position = text.indexOf(heading);
    assert.ok(position > previous, `${heading} must follow the previous section`);
    previous = position;
  }
  assert.match(text, /operation\?\.selected_count \?\? selected\.size/);
  assert.match(text, /candidate\.line_linked === false/);
  assert.match(text, /validation\.sendable_count/);
  assert.match(text, /問題ありません/);
  assert.match(text, /問題があります/);
  assert.match(text, /検証してください/);
  assert.match(text, /検証中/);
  assert.match(text, /send-problem-details" role="alert"/);
  assert.match(text, /new Set<string>\(\)/);
  assert.match(text, /送信後は取り消せません。実LINE検証は送信可能な1名に限定されます/);
  assert.match(text, /formatBlockingReasons\(lineSendMode\)/);
  assert.doesNotMatch(text, /<h3>4\. 送信モード|<h3>5\. 注意事項|通知内容の確認|実LINE送信可能：/);
  const css = await readFile(new URL("./admin.css", import.meta.url), "utf8");
  assert.match(css, /compact-send-secondary\{display:grid;grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
  assert.match(css, /compact-send-primary[^}]*width:100%/);
  assert.doesNotMatch(css, /compact-send-confirmation[^}]*overflow/);
});

test("existing handlers are received rather than replacing API workflow", async () => {
  const text = await source();
  for (const callback of ["select", "toggle", "begin", "save", "validate", "send", "revalidate", "targets"]) assert.match(text, new RegExp(`${callback}:`));
  assert.doesNotMatch(text, /fetch\(|adminApi\.|createOperation|updateOperation|updateTargets/);
});

test("validated non-terminal operation exposes one edit action only in panel three", async () => {
  const text = await source();
  const page = await readFile(new URL("./page.tsx", import.meta.url), "utf8");
  const summary = text.slice(text.indexOf("export function MessageReadOnlySummary"), text.indexOf("export function SendConfirmationPanel"));
  const confirmation = text.slice(text.indexOf("export function SendConfirmationPanel"), text.indexOf("export function SendPreparationState"));
  assert.match(summary, /edit && <div className="message-readonly-actions"/);
  assert.match(summary, /onClick=\{edit\}/);
  assert.match(page, /step === "confirm" && validation !== null && validationCurrent && !workflowState\.terminal && workflowAction !== "sending" \? \(\) => setStep\("edit"\)/);
  assert.doesNotMatch(confirmation, /通知文編集|通知文を再編集|本文を編集|onClick=\{edit\}/);
  assert.equal((text.match(/>通知文編集<\/button>/g) ?? []).length, 1);
});

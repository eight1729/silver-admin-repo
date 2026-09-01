import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

async function sources() {
  const [shell, panel, page, css, lowerPanels, panels] = await Promise.all([
    readFile(new URL("./AdminShell.tsx", import.meta.url), "utf8"),
    readFile(new URL("./AdminPanel.tsx", import.meta.url), "utf8"),
    readFile(new URL("./page.tsx", import.meta.url), "utf8"),
    readFile(new URL("./admin.css", import.meta.url), "utf8"),
    readFile(new URL("./LowerPanels.tsx", import.meta.url), "utf8"),
    readFile(new URL("./MajorPanels.tsx", import.meta.url), "utf8"),
  ]);
  return { shell, panel, page, css, lowerPanels, panels };
}

test("common header and sidebar identify the notification workspace", async () => {
  const { shell } = await sources();
  assert.match(shell, /スタッフ管理画面/);
  assert.match(shell, /求人通知・マッチング管理/);
  for (const label of ["ダッシュボード", "求人一覧", "通知作成", "送信履歴", "レポート", "設定"]) assert.match(shell, new RegExp(label));
  assert.match(shell, /aria-current=\{current \? "page" : undefined\}/);
  assert.match(shell, /usePathname/);
  for (const route of ["/admin/dashboard", "/admin/jobs", "/admin", "/admin/history", "/admin/reports", "/admin/settings"]) assert.match(shell, new RegExp(`href: "${route.replaceAll("/", "\\/")}"`));
  assert.doesNotMatch(shell, /disabled aria-disabled="true"|後続Stepで実装/);
});

test("all six panel headings are present in operation order", async () => {
  const { page, lowerPanels } = await sources();
  const headings = ["求人選択", "対象候補会員", "通知文編集", "送信前確認", "配信状況サマリー", "最近の操作履歴"];
  let previous = -1;
  for (const heading of headings) {
    const position = page.indexOf(`title="${heading}"`);
    assert.ok(position > previous, `${heading} must follow the previous panel`);
    previous = position;
  }
  assert.equal((page.match(/<AdminPanel number=/g) ?? []).length, 6);
  assert.match(lowerPanels, /通知を作成すると、このoperationの配信状況が表示されます。/);
  assert.match(lowerPanels, /通知operationを作成すると、この画面で確認できる操作を表示します。/);
  assert.match(page, /<DeliverySummaryPanel[\s\S]*<RecentOperationHistory/);
  assert.doesNotMatch(page + lowerPanels, /開封率|反応率|興味あり|ダミー履歴/);
});

test("PC workspace groups panels into upper, left-stack, and lower regions", async () => {
  const { page } = await sources();
  assert.match(page, /className="admin-upper-workspace"/);
  assert.match(page, /className="admin-left-stack"/);
  assert.match(page, /className="admin-lower-workspace"/);
  assert.match(page, /admin-upper-workspace[\s\S]*admin-left-stack[\s\S]*number=\{1\}[\s\S]*number=\{2\}[\s\S]*number=\{3\}[\s\S]*number=\{4\}/);
  assert.match(page, /admin-lower-workspace[\s\S]*number=\{5\}[\s\S]*number=\{6\}/);
});

test("queue failure detail stays inside panel four and outside grid auto-placement", async () => {
  const { page, panels } = await sources();
  const panelFour = page.indexOf("<AdminPanel number={4}");
  const queueFailureProp = page.indexOf("queueFailure={queueFailure}", panelFour);
  const panelFourEnd = page.indexOf("</AdminPanel>", panelFour);
  const panelFive = page.indexOf("<AdminPanel number={5}");
  assert.ok(panelFour < queueFailureProp && queueFailureProp < panelFourEnd);
  assert.ok(panelFourEnd < panelFive);
  assert.match(panels, /if \(queueFailure\) problems\.add\("送信処理は開始されていません。自動再送は行いません。"\)/);
  assert.match(panels, /send-problem-details" role="alert"/);
});

test("panel shell provides labelled structure, status and action slots", async () => {
  const { panel } = await sources();
  assert.match(panel, /aria-labelledby=\{headingId\}/);
  assert.match(panel, /admin-panel-number/);
  assert.match(panel, /admin-panel-status/);
  assert.match(panel, /actions/);
  assert.match(panel, /admin-panel-body/);
  assert.match(panel, /description\?: string/);
  assert.match(panel, /\{description && <p>\{description\}<\/p>\}/);
});

test("notification workspace omits the top step status and all six panel descriptions", async () => {
  const { page, css, lowerPanels } = await sources();
  for (const text of [
    "通知を作成する求人を1件選択します。",
    "選択求人の通知候補を確認し、対象を選択します。",
    "通知本文を編集し、下書き保存と事前検証を行います。",
    "送信条件と検証結果を確認します。",
    "現在のoperationに属する配信結果を確認します。",
    "現在のoperationで確認できる操作だけを表示します。",
  ]) assert.doesNotMatch(page, new RegExp(text));
  assert.doesNotMatch(lowerPanels, /現在のoperationと、この画面を開いている間に確認できた操作だけを表示します。正式な監査履歴ではありません。/);
  const workspace = page.slice(page.indexOf("return <AdminShell"), page.indexOf("function Jobs"));
  assert.doesNotMatch(workspace, /stepTitle\(step\)|statusLabel\(operation\.status\)|className="admin-toolbar"/);
  assert.match(workspace, /allowDemoReset && <div className="admin-toolbar-actions"/);
  assert.match(css, /admin-toolbar-actions\{display:flex;justify-content:flex-end;margin-bottom:\.5rem\}/);
  for (let panel = 1; panel <= 6; panel += 1) assert.match(workspace, new RegExp(`<AdminPanel number=\\{${panel}\\} title=`));
});

test("mode presentation distinguishes Fake, live ready and live blocked without identifiers", async () => {
  const { shell } = await sources();
  assert.match(shell, /label: "Fake"/);
  assert.match(shell, /label: "実LINE送信可能"/);
  assert.match(shell, /label: "実LINE送信ブロック中"/);
  assert.doesNotMatch(shell, /member_id|service_id|line_subject|access token|Authorization|LIFF ID/);
});

test("responsive navigation and panel order remain accessible", async () => {
  const { shell, css } = await sources();
  assert.match(shell, /aria-label=\{menuOpen \? "メニューを閉じる" : "メニューを開く"\}/);
  assert.match(shell, /aria-expanded=\{menuOpen\}/);
  assert.match(shell, /aria-controls="admin-sidebar-navigation"/);
  assert.match(shell, /aria-label="スタッフ管理メニュー"/);
  assert.match(css, /\.admin-upper-workspace\{[^}]*grid-template-columns:minmax\(420px,1\.35fr\)[^}]*minmax\(340px,1fr\)[^}]*minmax\(310px,\.95fr\)/);
  assert.match(css, /\.admin-left-stack\{[^}]*grid-template-rows:auto minmax\(0,1fr\)/);
  assert.match(css, /\.admin-lower-workspace\{[^}]*grid-template-columns:minmax\(0,1\.1fr\) minmax\(0,1fr\)/);
  assert.match(css, /@media\(max-width:1359px\)/);
  assert.match(css, /@media\(max-width:760px\)/);
  assert.match(css, /\.admin-upper-workspace,\.admin-left-stack,\.admin-lower-workspace\{grid-template-columns:minmax\(0,1fr\)/);
  assert.doesNotMatch(css, /grid-template-areas|grid-area:/);
  assert.doesNotMatch(css, /\border\s*:/);
  assert.match(css, /focus-visible/);
  assert.match(css, /prefers-reduced-motion/);
});

test("existing workflow handlers remain connected inside the panels", async () => {
  const { page } = await sources();
  for (const handler of ["requestJobSelection(jobId)", "begin={beginOperation}", "save={saveMessage}", "validate={validate}", "send={fakeSend}", "retry={loadDeliveriesOnly}"]) assert.ok(page.includes(handler), `${handler} remains connected`);
  assert.match(page, /lineSendMode=\{lineSendMode\}/);
  assert.match(page, /canSend=\{workflowState\.canSend\}/);
});

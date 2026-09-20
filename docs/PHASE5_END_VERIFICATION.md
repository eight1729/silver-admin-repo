# Phase 5 End Verification

検証日: 2026-09-20。対象は `silver-admin-repo` と `silver-line-repo`。
最初に既存コードを読み、既報の focused suites を再実行した後、再現した競合と明確な ownership 契約違反のみ修正した。
実 DB、実ネットワーク、実 `.env`、旧 monorepo は使用していない。Git branch/commit/push/remote 操作なし。

## 1. Overall Result

**VERIFIED_WITH_FIXES**。

Phase 5 の自動 dispatch/recovery/reconciliation と terminal convergence をコード・オフライン SQL tests で確認した。
修正は §15 の 3 点。実環境未実施と UI metadata の注意は §16–17 に分離する。
コードレベルの最終判定は **ROADMAP_CODE_COMPLETE_WITH_NOTES**。

## 2. Slice 5.1 Integration

`app.main_admin:app` の configured standard composition は、CurrentDbExternalBusinessGateway、
AdminApplicationService、HTTP LINE Internal API client、SQL repository、dispatcher、
AdminLineResultReconciler、AdminNotificationRunner を共有する。

runner ownership は `ADMIN_NOTIFICATION_RUNNER_SERVICE_IDS`。`ADMIN_INTERNAL_API_SCOPES` は
organization 解決・inbound authorization の設定であり、その全件を runner 対象に変換しない。
standard composition は専用 ownership の各 ID を exact lookup する。wildcard/default service fallback はない。
helper の省略時 scope 推論も今回除去した。ownership 未設定では Staff application は fail-closed の未構成経路。

runner は lifespan startup で start、shutdown で cancel/await。import 時に task を起動しない。
send request の durable outbox が起点で、frontend GET や manual reconcile を必要としない。

## 3. Slice 5.2 Integration

`app.main_line:app` は共有 LineNotificationRuntime と LineCommandRecoveryRunner を構成する。
command acceptance は DB commit 後に 202。BackgroundTasks が失われても SQL recoverable query と runner が再処理する。

new provider attempt は command row lock の下で snapshot と同時予約する。snapshot は recipient と順序付き messages の JSON。
credential は含まない。provider call より先に persist する。
同じ command_id/attempt_number は UUID5 retry key と同じ persisted body を使う。restart/config 変更で再生成しない。
Command sender の retry_key は必須で、key 無し compatibility fallback はない。

409 + 非空 `x-line-accepted-request-id` は SENT に収束する。generic 409 は FAILED。
retry window は **24 時間 − 30 秒 margin**。期限以上または負の age、missing/invalid legacy snapshot は provider call なしで UNKNOWN。
timeout/5xx は同じ PENDING attempt を保持する。
latest SENT/FAILED/UNKNOWN は SQL query の LIMIT 前に recovery 候補から除外する。

startup/start、shutdown/cancel/await と standard runtime の共有 ownership は既存 tests で確認した。

## 4. Slice 5.3 Integration

Admin は operation lock、60 秒 lease、claim token で 1 件ずつ claim する。
有効 lease は取得できず、期限以下または legacy NULL lease は同じ logical command を再取得できる。
token が一致しない旧 worker の outcome write は no-op。

retryable submission failure は delivery PENDING を保持する。
permanent failure は outbox PERMANENT_FAILURE と delivery FAILED を同じ transaction で確定して再集計する。
LINE terminal result は delivery、RECONCILED outbox、aggregate/audit を同じ transaction で更新する。
terminal outbox は poll しない。重複反映は no-op。

pending が残れば SENDING、全 SENT は COMPLETED、FAILED/UNKNOWN/SKIPPED を含めば COMPLETED_WITH_ERRORS。
CANCELLED と未予約/空 operation を誤って完了させない。completed_at は初回 terminal 確定時のみ設定し、既存値を保持する。

予約後の編集・target replacement・validation を service と repository の両方で拒否する。
今回、予約直前の編集も optimistic snapshot 比較を operation lock 内で検出するようにした。
送信前 revalidation と予約の間に編集された場合は 409 相当の conflict とし、古い outbox を作らない。

## 5. Full Notification State Flow

Admin operation → target validation → snapshot を持つ durable outbox → Admin runner → lease claim →
HTTP LINE command submission → LINE command persistence/202 → BackgroundTasks または recovery runner →
canonical `line_recipient_linkages` → provider request snapshot の atomic reservation →
同じ retry key を付けた LINE Messaging request → LINE result projection → Admin reconciler →
delivery terminal / outbox RECONCILED → operation aggregate / completed_at。

cross-repository test では、stale Admin claim から同じ command の JSON を LINE repository の実装へ渡す。
canonical linkage を SQL に保存し、provider 受理直後の commit 前 crash を挟み、再構成した LINE runner が
同じ snapshot/key で replay する。mock provider の実効受理は 1 件。
その result JSON を Admin に戻し、COMPLETED/RECONCILED/completed_at と次回 poll 除外を確認した。
両方の `app` package を混ぜないため LINE 部分だけ別 Python process で実行した。実 HTTP/実 DB の E2E ではない。

## 6. State Recovery Matrix

| State | Recoverable | Terminal | Who / automatic next action |
| --- | --- | --- | --- |
| Admin outbox pending | Yes | No | Admin runner が claim/submit |
| Admin delivering、有効 lease | 待機 | No | owner が outcome 確定。別 worker は取得不可 |
| Admin delivering、期限切れ/旧 NULL | Yes | No | 同じ command identity で reclaim |
| Admin retryable_failure | Yes | No | 次 cycle に再 submit、delivery は pending |
| Admin accepted | Yes | No | LINE result を poll |
| Admin permanent_failure | No submit | Yes | FAILED delivery と aggregate を確定/旧不整合修復 |
| Admin reconciled | No | Yes | submit/poll なし |
| LINE command accepted/pending、attempt なし | Yes | No | canonical recipient 解決→attempt 予約 |
| LINE recipient_not_linked | No | Yes | result を返す。provider attempt を作らない |
| Provider PENDING、期限内 | Yes | No | 同じ snapshot/key を replay |
| Provider PENDING、期限外/legacy body 不明 | 判定処理のみ | UNKNOWN へ | provider call なしで mark_unknown |
| Provider SENT | No | Yes | result projection のみ、再送なし |
| Provider FAILED / UNKNOWN | No automatic retry | Yes | result projection のみ、新 attempt なし |
| Admin delivery PENDING | Yes | No | submit/reconcile を待つ |
| Admin SENT/FAILED/UNKNOWN/SKIPPED | No | Yes | aggregate 計算へ |
| Admin COMPLETED / COMPLETED_WITH_ERRORS | No | Yes | completed_at を保持 |

LINE command row 自体が accepted のままでも、latest provider delivery が terminal なら result は terminal であり、
recovery query から除外される。command status と provider result を同一視しない。

## 7. Cross-Repository Contract

Admin→LINE: HTTP-only v1 NotificationCommand/NotificationResult。external member/service/organization IDs を使用。
LINE→Admin: v1 member verification/summary/recommended jobs/job detail の HTTP client と scope/auth を維持する。

両 repository の Admin Internal v1 / LINE Internal v1 artifact は JSON 完全一致。
canonical linkage は `line_recipient_linkages`。通知 pipeline と canonical LIFF runtime は同じ SQL store を使い、
`line_member_links` へ fallback しない。LINE subject、provider snapshot、provider credential は Admin 境界へ出ない。

## 8. Runtime Composition

| Entry point | Ownership | Startup / shutdown |
| --- | --- | --- |
| main_admin | app composition が 1 Admin runner を保持。専用 service IDs | lifespan start、stop は cancel/await |
| main_line | app.state.line_runtime が 1 recovery runner を保持。HTTP dependency override も同じ runtime | lifespan start、stop は cancel/await |

constructor/import は task を作らない。DB/HTTP client は共有し、shutdown で閉じる。
environment による provider send の production/staging/disabled policy は維持し、business source を Fake に切り替えない。

## 9. API / OpenAPI

- Admin Staff v1: runtime generated schema と checked-in artifact が完全一致。
- Admin Internal v1: runtime generated schema と artifact が完全一致。
- LINE Public v2: runtime generated schema と artifact が完全一致。
- LINE Internal v1: provider contract artifact と生成 schema が完全一致。
  actual runtime router の paths/components も description を除けば完全一致。
  contract-only の説明文と runtime の説明文の違いは既存 metadata 差であり、wire 差ではない。

今回 public route/schema/artifact は変更していない。request_snapshot/claim_token/lease_expires_at は public/internal API に露出しない。
LINE public v1 は historical reference であり、current canonical API は v2。

## 10. DB / Migration

| Repository | Phase 5 addition | Application expectation / legacy |
| --- | --- | --- |
| LINE | line_provider_deliveries.request_snapshot JSON NULL | 新 attempt は必須。旧 NULL/invalid は推測再生成せず UNKNOWN |
| Admin | admin_notification_outbox.lease_expires_at TIMESTAMP WITH TIME ZONE NULL、claim_token TEXT NULL | 新 claim は両方設定。旧 delivering NULL lease は reclaim |

既存 provisioning scripts から idempotent additive migration を呼ぶ。既存 identity/body の backfill/reset はしない。
今回の verification fixes に新しい DB column/migration はない。actual DB に適用していない。
old workers を drain → 両 migration → new application 起動の順序が必要。
LINE runner は startup で自動起動するため、migration 完了前に新 application を起動してはいけない。
Admin も ownership 設定済み new application の startup が runner activation になる。

## 11. Focused Tests

| Suite | Passed | Failed | Skipped | Deselected | Exit code |
| --- | ---: | ---: | ---: | ---: | ---: |
| Admin Phase 5 + end verification | 127 | 0 | 0 | 0 | 0 |
| LINE Phase 5 + race regression | 117 | 0 | 0 | 11 | 0 |
| LINE canonical LIFF / deep link boundary | 61 | 0 | 0 | 0 | 0 |
| LINE→Admin consumer / linkage boundary | 35 | 0 | 0 | 0 | 0 |
| Total（重複なしの最終 suite） | 340 | 0 | 0 | 11 | 全て 0 |

変更前の baseline も Admin 123 passed、LINE 115 passed/11 deselected、exit 0 を再確認した。
追加は Admin 4 tests、LINE 2 parameterized cases。LINE race は修正前に 2 ケースとも失敗し、修正後に成功した。
11 deselected は live integration tests で、実 PostgreSQL などの Manual Gate に属する。

実行は `python -B` + `pytest -p no:cacheprovider -q --tb=short -m "not integration"`。
settings import 前に DotEnvSettingsSource を無効にし、process-local の dummy DATABASE_URL/APP_ENV を設定した。
実環境ファイルは読んでいない。test doubles/mock HTTP は tests のみで使用した。

## 12. Concurrency / Crash Verification

Admin: active lease、期限境界、NULL legacy lease、reclaim 後の古い token、2 worker、atomic rollback、
並行 terminal reconcile/audit、予約競合、runner 中断と再開を SQL repository tests で確認した。
LINE: command reservation race、snapshot authority、retry accepted 409、config 変更後 replay、
provider 受理直後 crash、terminal exclusion、および今回の宛先未連携/予約競合の両順序を確認した。

SQLite async bridge で business invariants を検証した。PostgreSQL row lock の実並行性、Cloud Run instance 間競合は未実施。
HTTP replay はあり得るが same logical command / same provider retry key を維持する。
「HTTP call が常に 1 回」とは判定していない。

## 13. Security / Privacy

canonical subject は LINE 内の linkage/snapshot にのみ保存し、Admin は business member ID と linked boolean を扱う。
result projection は明示フィールドだけを返し、snapshot/raw message/provider credential を含めない。
Phase 5 runner/background ログは例外の型のみ。今回 raw payload/secret をログへ追加していない。
actual `.env` / `.env.line` / `.env.admin` や actual credential を読取り・変更していない。
checked-in artifacts に recovery metadata と Admin 向け LINE subject がないことも機械的に確認した。

## 14. Runtime Fake / Legacy Regression

configured notification runtime の business adapter は CurrentDbExternalBusinessGateway、
LINE recipient は SqlAlchemyLineRecipientStore、送信は HttpLineCommandSender。
Fake runtime / fixed M001 / legacy linkage fallback はこの経路に存在しない。
M001 を用いる既存 fixture は offline test data である。
canonical LIFF frontend は LINE API base と verified ID token / explicit service context を使う。
staging の送信制限は business source の切替ではない。

## 15. Fixes Made During Verification

1. **LINE terminal decision / provider reservation race**。
   2 workers が異なる linkage 状態を読み、先に SENT となった結果を recipient_not_linked に隠す、
   または recipient_not_linked 確定後に provider send を開始するケースを再現した。
   command row の同じ lock で両決定を排他化し、既存 provider reservation を優先、未連携確定後の予約を拒否する。
   pipeline は競合の勝者の result を返す。
   変更: LINE `line_notification_command_repository.py`、`line_provider_delivery_store.py`、`line_notification_pipeline.py`。
2. **Admin 予約直前の編集競合**。
   service の再 validation 結果と現在 operation を確認し、begin_send_attempt の operation lock 内で
   expected_operation と保存状態を比較する。古い snapshot を予約する前に拒否する。
   変更: Admin `notification_service.py`、SQL repository、repository port、対応する test-only memory repository。
3. **Admin ownership の推論 fallback**。
   standard caller は専用 IDs を渡していたが、composition helper に scope 全件への省略時 fallback が残っていた。
   runner_service_ids を明示必須にし、organization mapping から execution ownership を推論しない。
   変更: Admin `runtime/admin_line.py` と呼出し test。

追加 tests: Admin `backend/tests/test_phase5_end_verification.py`、LINE `backend/tests/test_phase5_end_races.py`。
大規模 refactor、UI redesign、新 framework、新 Phase/Slice、API artifact 変更は行っていない。

## 16. Notes

- 実 PostgreSQL/Cloud Run/LINE は未検証。clock 同期、CPU allocation、runner 稼働、throughput は実配備確認が必要。
- LINE の長期間 configuration error や外部依存障害は正しい runtime config の回復が前提。
  今回 broader retry policy / observability / performance tuning は追加していない。
- Staff API の既存 `/line-send-mode` は local integration 以外で legacy `fake` 表示 metadata を返す。
  configured production notification runtime に Fake sender があるという意味ではない。
  UI には「実 LINE 送信なし」の旧表示もあるため、本番 UI 公開前に実挙動との整合を確認すること。
  この既存表示経路は通知 state machine を変更しないが、操作者が表示だけで送信有無を判断してはいけない。
  今回は backend reliability verification と分離し、UI redesign/metadata contract 拡張を実施していない。
- LINE Internal contract の Phase 1 の説明文、historical public v1 artifact は残る。wire schema は一致しており、無関係な docs cleanup はしない。

## 17. Manual Gate Checklist

1. 対象 DB/backup、service ownership、organization mapping、credentials/URLs、時刻同期、
   Cloud Run background CPU/instance lifecycle を確認する。本番 UI の送信モード表示も実送信前に確認する。
2. 旧 Admin/LINE workers を drain/停止し、旧版と新版の同時処理を避ける。
3. LINE snapshot migration と Admin lease/token migration を実 PostgreSQL へ適用し、column と既存 rows を確認する。
4. 新 LINE application を正しい config で起動する。startup が recovery runner activation である。
5. 新 Admin application を専用 ownership 設定で起動する。startup が Admin runner activation である。
6. actual Admin↔LINE HTTP/auth、canonical linkage、current verification DB/External Business adapter/API を確認する。
7. Cloud Run multiple instance、process kill/restart、同じ command/key/body、24h window の復旧と terminal exclusion を確認する。
8. 実 LINE Messaging API の retry-key/accepted 409、通知受信、Admin completed_at/aggregate を確認する。
9. browser/LIFF の本人確認・求人・会員連携・送信 preview/表示を含む実業務通し確認後に公開判断する。

## 18. Roadmap Implementation Status

| Phase | 実装/既存 Verification | 今回の扱い |
| --- | --- | --- |
| 1 Canonical Business Boundary | 3 slices COMPLETE / VERIFIED | Internal boundary static・consumer regression |
| 2 Canonical LINE Backend | 2 slices COMPLETE / VERIFIED | linkage / LINE runtime regression |
| 3 Canonical LIFF Frontend | 2 slices COMPLETE / VERIFIED | canonical backend/contract regression、frontend static |
| 4 Production-shaped Runtime Unification | 2 slices COMPLETE / VERIFIED_WITH_NOTES | standard composition / provider / lifecycle 確認 |
| 5 Notification Production Reliability | 3 slices COMPLETE_WITH_NOTES | 今回 VERIFIED_WITH_FIXES |

Phase 1–4 の結果は既存完了記録を引き継ぎ、今回フルの過去 Verification をやり直したという意味ではない。
全 12 slices のコード実装工程は完了。実運用公開の承認とは分離する。

## 19. Final Roadmap Code-Level Judgment

**ROADMAP_CODE_COMPLETE_WITH_NOTES**。

この Word ロードマップのコード実装工程は完了と判断し、ここで停止する。
新しい Phase/Slice や追加 hardening は開始しない。次は §17 の Manual Gate / external integration。

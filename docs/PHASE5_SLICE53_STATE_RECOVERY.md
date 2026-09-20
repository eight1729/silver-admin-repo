# Phase 5 Slice 5.3 — State Recovery / Consistency / Final Gate

判定: **COMPLETE_WITH_NOTES**。Phase 5 End Verification は未実施。

## 実装範囲と現状との差分

Admin の SQL repository、dispatcher、reconciler、runner、予約後編集規則を変更した。
従来の delivering は期限情報がなく停止後に残り続けた。permanent_failure は outbox のみを更新し、
terminal LINE result は delivery のみを更新して accepted を残した。
今回、claim の回収と fencing、delivery/outbox/operation のトランザクション更新を追加した。
LINE は既存 result projection を確認し、Slice 5.2 の回帰のみを実施。LINE source の変更はない。

## 状態遷移

| 起点・結果 | Outbox | Delivery | Operation |
| --- | --- | --- | --- |
| pending / retryable_failure を claim | delivering | pending | 既存状態 |
| delivering、lease 有効 | 他 worker は claim 不可 | 変更なし | 変更なし |
| delivering、期限以下または旧 NULL lease | 同じ command を再 claim | pending | 復旧継続 |
| retryable submission failure | retryable_failure | pending | sending |
| permanent submission failure | permanent_failure | failed | 再集計 |
| command submit 成功 | accepted | pending | sending |
| LINE accepted / pending | accepted | pending | sending |
| LINE sent | reconciled | sent | 再集計 |
| LINE failed / rejected | reconciled | failed | 再集計 |
| LINE unknown | reconciled | unknown | 再集計 |
| LINE recipient_not_linked | reconciled | skipped | 再集計 |

既存 HTTP client の分類を維持する。transport/timeout/5xx は retryable、4xx（認証・validation・409 を含む）
は permanent。provider の UNKNOWN は Admin の成功ではなく terminal non-success。
永久 submission failure の安全な error_code は `line_submission_permanent_failure`。
HTTP 応答本文・credential・member 情報を新しいログへ出さない。

## Lease / crash / duplicate prevention

- 追加 field は nullable `lease_expires_at` と `claim_token` の 2 つ。
- operation row を `FOR UPDATE` でロックしてから outbox を選び、1 件だけ 60 秒 lease で取得する。
- HTTP submit は 30 秒上限。process kill や cancellation で結果更新前に停止しても、期限後に回収する。
- 回収時も persisted command_id / target_id / idempotency_key / payload snapshot を変更しない。
- claim ごとに token を更新し、submission 結果更新は delivering と token の一致が必要。
  古い worker の遅延応答で新しい worker の結果を上書きしない。
- retryable failure は lease を現在時刻で終了し、その時刻を取得順にも使う。
  未取得 target を優先し、その後は古い終了時刻から選び、先頭失敗 target による滞留を避ける。
- crash 境界では同じ command の HTTP 再送はあり得る。LINE の既存 command idempotency と
  Slice 5.2 の provider retry key / request snapshot により同じ論理通知として扱う。
  「HTTP が必ず 1 回」という保証ではない。

## Atomicity / idempotency / aggregate

submission state と permanent failure delivery、terminal result の delivery/outbox、および aggregate/audit は
それぞれ 1 transaction で更新する。operation lock の取得順を共通化した。
terminal reconcile は accepted のみを対象とし、reconciled/permanent_failure は poll しない。
同じ結果の並行反映でも 2 回目は no-op。delivery の既存 terminal 値を上書きしない。

現在の Admin→LINE boundary の規則を維持する: pending があれば SENDING、全 delivery が SENT なら COMPLETED、
それ以外（FAILED/UNKNOWN/SKIPPED）は COMPLETED_WITH_ERRORS。CANCELLED は保持する。
未予約または delivery が空の operation を完了扱いしない。
terminal aggregate の最初の確定時に completed_at を設定し、既存値を保持する。
aggregate に変化がある場合のみ audit を追加する。
旧 permanent_failure + pending delivery はローカル再集計時に修復する。

## Mutation / snapshot

send_requested_at がない DRAFT/READY は従来通り編集・対象変更・validation が可能。
予約後は service の全編集入口で拒否する。repository でも operation lock 内で
message/version/hash/job/validation/send_requested_at の変更と target replacement を拒否する。
予約前に読んだ古い editor の書込みも送信予約を解除できない。
durable outbox がある予約の rollback も拒否する。
repository で検出した予約競合は既存 HTTP 409 operation_conflict へ写像する。
dispatcher は常に保存済み outbox snapshot を使う。

## Standard runtime / bounded runner

既存 main_admin の configured production composition に 1 runner があり、application/dispatcher/reconciler と
同じ repository を使う。専用設定 `ADMIN_NOTIFICATION_RUNNER_SERVICE_IDS` と既存 organization scope が必要。
Fake business adapter や frontend GET/manual reconcile を実行条件にしない。

5 秒ごとの cycle で service ごとに最大 50 operations を keyset pagination で取得する。
operation ごとに submit は 1 件、result poll は最大 50 件。poll のページも循環し pending target による滞留を避ける。
送信・poll・service 選択の例外を分離し、例外の型だけをログへ記録する。
start は重複 task を作らず、stop は task を cancel して完了まで await する。
lifespan の異常終了時も runner、engine、HTTP client を順に cleanup する。
Cloud Run の CPU/instance lifecycle で runner が動く実配備条件は Manual Gate。

## Migration / deployment 手順（今回は未適用）

既存の `backend/scripts/provision_admin_notification_tables.py` が呼ぶ
`create_admin_notification_tables()` に additive migration を組み込んだ。
既存 5 tables 以外は作成しない。新設 table は最初から 2 fields を持つ。

1. 古い Admin workers と旧 deployment の traffic を停止する。混在運用は不可。
2. 対象 DB と backup を確認し、既存 provisioning 手順を実施する。
3. PostgreSQL では `lease_expires_at TIMESTAMP WITH TIME ZONE NULL` と `claim_token TEXT NULL` を追加する。
   repeat 実行は既存 column を検出して変更しない。既存 command identity/body は更新しない。
4. 旧 delivering の NULL lease は新 runner の回収候補となる。
5. 新 Admin deployment の専用 runner scopes、internal API 接続設定、ログ、復旧状況を確認する。

新 broker/framework、LINE DB migration、public API field/OpenAPI artifact の変更はない。
実 `.env` / `.env.admin` / `.env.line` の読取り・変更、Git branch/commit/push、実通知送信は行っていない。

## Focused verification

主要変更ファイル（Admin repository 内）:

- `backend/app/db/admin_notification_repository.py`: lease claim、fencing、atomic projection、aggregate、編集防止。
- `backend/app/db/admin_tables.py` / `admin_notification_provisioning.py`: nullable metadata と additive migration。
- `backend/app/domain/models/admin_notification.py`: RECONCILED と lease/token。
- `backend/app/domain/ports/admin_notification_repository.py` / `domain/errors/admin_notification_repository.py`: repository 契約と予約競合。
- `backend/app/application/admin_line_dispatch.py`: fenced dispatch と terminal reconciliation。
- `backend/app/application/admin_notification_runner.py` / `backend/app/app_factory.py`: bounded recovery と lifecycle。
- `backend/app/application/notification_service.py` / `backend/app/api/routes/admin.py`: 編集禁止と HTTP 409。
- `backend/tests/test_admin_state_recovery.py`: SQL・crash・concurrency・標準 runtime 試験。
- `backend/tests/test_admin_line_dispatch.py` / `test_admin_persistence_provisioning.py` / `test_admin_local_integration.py`: 既存回帰の更新。

Admin: 123 passed / 0 failed / 0 skipped / 0 deselected、exit code 0。
LINE: 115 passed / 0 failed / 0 skipped / 11 deselected、exit code 0。
合計: 249 collected、238 passed、11 deselected。
LINE の deselected は live integration tests。pytest cache と bytecode 出力を止め、dotenv source を
無効にし、ダミーの process-local DATABASE_URL で実行した。

Admin 対象: test_admin_state_recovery、test_admin_line_dispatch、test_admin_persistence_provisioning、
test_admin_line_boundary、test_admin_line_internal_client、test_admin_internal_api、
test_admin_local_integration、test_canonical_runtime_provider、test_phase5_admin_oidc_rbac。
LINE 対象: Slice 5.2 request snapshot recovery/pipeline/sender/staging sender/provider foundation/
result service/command core/internal contract/recipient resolution/provisioning。

新しい SQL tests は実 SQLAlchemy repository を SQLite の async bridge で実行する。
active claim、期限境界、旧 NULL lease、古い token、2 workers、再送 identity、retry/permanent、
全 result states、二重 reconcile/audit、transaction rollback、mixed/empty/cancelled aggregate、
completed_at の保持、編集競合、予約 idempotency、runner paging・例外分離・停止中断を確認する。
standard main_admin + production composition + mock HTTP の試験で、手動 reconcile なしの UNKNOWN 収束も確認する。
SQLite bridge の直列化は PostgreSQL の row lock 検証の代替ではない。

## Static review / remaining gates

確認済み: persisted identity/snapshot の維持、active lease 保護、stale 回収、fenced outcome、
permanent failure 伝搬、terminal polling 除外、atomic projection、idempotent audit/completed_at、
UNKNOWN non-success、予約後変更拒否、bounded runner と cleanup、production Fake 依存なし。

Manual Gate: 実 PostgreSQL migration/locking、Cloud Run multiple instances、process kill/restart、
実 credentials/network/LINE Messaging API/External Business API、UI 操作と実通知受信。
実行環境の時刻同期、runner 稼働と throughput、配備中の old/new worker 混在排除も確認する。

Phase 5 End Verification に残すもの: 上記 Manual Gate と、予約→Admin recovery→LINE provider recovery→
Admin terminal 表示の実環境通し確認。今回は Slice 5.3 focused verification までで停止する。

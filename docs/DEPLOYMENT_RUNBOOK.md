# Silver LINE / Admin Deployment Runbook

対象: PR待機中ロードマップ Phase 2 / Slice 2.3。全体手順のownerはAdmin repository。
対象unitはLINE Backend、Admin Backend、LINE / LIFF Frontend、Admin Frontend。
これは人間が後続の配備時に実行するチェックリストであり、配備済み・実接続検証済みという記録ではない。
チェック時は担当者・日時・対象revision/image・結果・機密を除いた証跡を別の運用記録へ残す。未確認は未チェックのままにする。

## 空の本番DBを構築する手順（12テーブル）

新規Supabaseプロジェクトには本節を適用する。既存プロジェクトは開発用として維持する。
以下は承認後に人間が実行する手順であり、実DB作成・DDL・初期登録・設定変更・配備の実施記録ではない。
既存DBを更新する場合のbackup / worker停止手順とは区別する。

### 準備条件と接続先の確認

- [ ] 新規の本番専用Supabaseプロジェクトと作業責任者を確定する。開発DBのdump/restoreやseedを流用しない。
  会員・求人・候補判定の正本はmigak HTTP APIとし、旧LINE連携・Command・Outbox・通知履歴・旧`silver-sumida`権限をコピーしない。
- [ ] 開発・本番でCloud Runサービス、DB資格情報、Secret ManagerのSecrets、実行サービスアカウントを分離する。
  本番サービスアカウントへ開発用Secretを渡さない。現行コードはDBの環境所属を自動照合しない。
- [ ] DDL実行前と配備前に、承認済み接続情報のプロジェクト識別子・接続host・database・role・schemaを人間が照合する。
  `APP_ENV=production`だけでは本番DBへの接続を保証しない。接続文字列や秘密値を証跡へ出さない。
  Admin / LINEは同じ本番DB・同じ対象schemaを使用し、双方向Internal APIのURLも同じ環境に揃える。
- [ ] PostgreSQL接続方式とdriver、TLS、DB roleの権限、`search_path`を確認する。metadataはschemaを明示しないため、
  作業用roleとruntime roleの解決先を揃える。別schemaに同名tableがある状態で続行しない。
  Supabase管理schemaは変更せず、以下12テーブルを置く対象schemaが空であることを確認する。
- [ ] 本番のRLS、Supabase公開APIへの露出・anon/authenticated権限、runtime role、DDL role、PK用sequenceの権限をDB担当者が確認する。
  本provisionerはこれらのsecurity設定を作成しない。`services`には署名Secretが入るため公開読取りを許可しない。
- [ ] 初期構築中は本番Admin runtime、LINE通知受付、recovery外部triggerを起動・公開しない。
  既存開発環境を停止・移行する手順ではない。Webhook URL・LINEチャネルの変更もこの作業に含めない。

### 対象テーブルと構築順序

正本は[Admin metadata](../backend/app/db/admin_tables.py)と
[LINE metadata](../../silver-line-repo/backend/app/db/tables.py)。業務members/jobs等は本番12テーブルに含めない。

| 順番 | テーブル | 用途・依存先 | 初期行 |
| --- | --- | --- | --- |
| 1 | `admin_notification_operations` | 通知操作・状態・検証snapshot | 不要 |
| 2 | `admin_notification_targets` | 対象選定、operation FK | 不要 |
| 3 | `admin_notification_deliveries` | Admin側結果、operation FK | 不要 |
| 4 | `admin_notification_audit_events` | 操作監査、operation FK | 不要 |
| 5 | `admin_notification_outbox` | 保存済みscope・Command・冪等性・lease、operation FK | 不要 |
| 6 | `staff_identities` | 検証済みOIDC本人・active | 承認したStaffのみ |
| 7 | `staff_service_permissions` | service別role、staff FK | 本人登録後、serviceごと |
| 8 | `line_recipient_linkages` | organization + service別の会員 / LINE subject連携 | 空から開始 |
| 9 | `line_notification_commands` | Command受付・冪等性・結果状態 | 不要 |
| 10 | `line_provider_deliveries` | 配信attempt・結果・再送snapshot、command FK | 不要 |
| 11 | `apps` | Webhook serviceの親レコード | 承認したapp |
| 12 | `services` | Webhook URLのservice識別子・active・署名Secret、app FK | 使用するserviceのみ |

通知operationのStaff ID、業務ID、canonicalのservice / organizationには業務tableや`services`へのFKはない。
4グループ間に作成順のFK依存はないが、次の固定順序で単独実行する。各グループ内の親→子順序はhelperが維持する。
Supabase自体の管理テーブル数ではなく、このアプリが所有するテーブルが12個であることを確認する。

承認したrevisionのsource checkoutとbackend依存環境を用意する。通常Backend imageは`app`のみCOPYし、`scripts`を含まない。
各CLIを実行する**前**に、そのprocessへ`APP_ENV=production`と承認済み`DATABASE_URL`を安全に供給する。
実dotenvや秘密値をリポジトリ・shell履歴・公開ログへ置かない。各コマンドは対応するbackendディレクトリで実行する。

| 順番 | 作業ディレクトリ | 手動コマンド | 対象 |
| --- | --- | --- | --- |
| 1 | `silver-admin-repo/backend` | `python scripts/provision_admin_notification_tables.py` | 通知5 |
| 2 | `silver-admin-repo/backend` | `python scripts/provision_admin_staff_tables.py` | Staff 2 |
| 3 | `silver-line-repo/backend` | `python scripts/provision_line_persistence_tables.py` | canonical 3 |
| 4 | `silver-line-repo/backend` | `python scripts/provision_line_webhook_tables.py` | apps → services |

既存3系統を再利用し、Webhook専用[helper](../../silver-line-repo/backend/app/db/line_webhook_provisioning.py)だけを追加した。
共有metadataの`create_all`、seed、起動時DDLは使用しない。新Webhook CLIはLINE ownerのDBでtransactionを開始し、終了時にengineをdisposeする。
初期行を登録せず、既存tableは`checkfirst=True`で保持する。成功表示はschema互換性の証明ではない。
既存tableが見つかった場合は実行前に列・型・NULL/default・PK・FK・unique・indexをmetadataと照合し、不一致なら停止する。
Webhook helperは不一致を検出・修復するmigrationではない。同一schemaへの逐次再実行はDDLや行更新を行わない。同時実行はしない。
既存通知helperのnullable lease/claim追加、LINE helperのnullable `request_snapshot` / `terminal_at`追加は従来どおり。
空DBでは最初から現在metadataの列を作成する。任意の旧schema修復や過去行のbackfillはしない。

### 初期行の手動登録

Staffは§2の既存`register_admin_staff.py`を使用し、検証済み実OIDC契約のissuer / subjectとUUID形式staff_idを登録する。
実ID Token自体を入力・保管しない。issuerのlookup表現は既存validatorと一致させる。
必要なserviceのみ`viewer` / `sender` / `admin`を付与する。旧Staff・旧権限をコピーしない。
Staff権限は人の認可、LINE scope設定はAdmin Backendからの要求の組織境界であり、相互に代用しない。

apps/servicesには既存の登録CLI・自動seedはない。DB担当者が承認した安全な登録経路で、parameter bindingを用いて
**apps → services**の順にtransaction内で登録し、重複PK・unique・FK違反は停止する。既存行を自動upsert・移行しない。
Secretを含むSQL文字列や入力値をshell履歴、共有SQL履歴、ログ、Gitへ残さない。登録経路の秘密情報取扱いを事前承認する。

| テーブル | 必須入力・制約 | 省略可能項目・用途 |
| --- | --- | --- |
| `apps` | `app_id` Text PK、`name` Text、`api_key_id` Text unique、`api_key_hash` Text、`active` Boolean。すべてNOT NULL | `created_at`はtimezone付き日時、DBのCURRENT_TIMESTAMP |
| `services` | `service_id` Text PK、`app_id` Text FK→apps、`display_name` Text、`active` Boolean。すべてNOT NULL | `created_at`はtimezone付き日時、DBのCURRENT_TIMESTAMP |
| servicesのnullable列 | Webhook有効化には`line_messaging_channel_secret` Textの非空値が必要 | `line_login_channel_id`、`liff_url`、`line_messaging_channel_access_token`はいずれもnullable Text |

`apps.api_key_id/api_key_hash`は既存schema上必須だが、現行Webhook/canonical経路はこれを認証に使用せず、
本repositoryにはhash生成・登録契約もない。管理元と承認済み登録値の決定をManual Gateとする。
不明なhash形式、仮キー、BearerやLINE Secretの代用品で埋めない。決定できるまで初期登録とWebhook有効化を停止する。
このgateは空schemaの準備とは別であり、新しいキー認証基盤を実装する指示ではない。

service識別子は`sandbox`または`sumida`を正確に登録する。
同じ承認済みappに複数serviceを関連付けられる。app ID / service ID / organization ID / LINE channel IDは別識別子。
organization列はservicesに存在しない。`sumida_shrc`をservice IDにせず、旧`silver-sumida`を別名として登録しない。
初期serviceは`active=false`とし、後述gate合格後に人間が有効化する。`apps.active=false`だけではWebhookを停止できない。
現行lookupは**service_id完全一致かつservices.active=true**のみを確認し、apps.activeを参照しない。

### 環境内の設定対応とWebhook有効化条件

設定値は実環境を確認して人間が供給する。以下は形式・論理対応だけで、実設定の適用指示ではない。

| 設定・保存先 | 形式・整合条件 |
| --- | --- |
| `ADMIN_INTERNAL_API_SCOPES` / `LINE_ADMIN_SERVICE_SCOPES` | JSON object、service→organization。対応は`{"sandbox":"sandbox","sumida":"sumida_shrc"}`。実際に有効化する組だけを明示する |
| `LINE_COMMAND_MESSAGING_ACCESS_TOKENS` | JSON object、organization→service→token文字列。上記の組に対応する承認済みMessaging tokenを安全に供給 |
| `LINE_CANONICAL_LIFF_ENTRY_BASES` | JSON object、organization→service→LIFF entry base文字列。同じ組と環境のLIFFを指す |
| `ADMIN_NOTIFICATION_RUNNER_SERVICE_IDS` | カンマ区切りservice ID。scopeに存在する担当serviceだけ。空値をrunner停止設定に使わない |
| `NEXT_PUBLIC_ADMIN_SERVICE_ID` / `staff_service_permissions.service_id` | 使用画面のserviceとStaffの許可serviceを一致させる。DB権限をUI設定で代用しない |
| `ADMIN_EXTERNAL_BUSINESS_BASE_URL` / `ADMIN_EXTERNAL_BUSINESS_AUDIENCE` | 本番12テーブルではHTTP URLが必須。audience省略時はbase URL。同一HTTP接続先が有効化する両organizationを扱えるか、migak側の契約と実疎通を確認 |
| `ADMIN_LINE_INTERNAL_API_BASE_URL` / `LINE_ADMIN_INTERNAL_API_BASE_URL` | 同じ環境の相手Backend URL。双方向Bearer対応は§3。開発のURL・credentialを本番へ持ち込まない |
| Staff OIDC / LINE Login / Frontend | §3・§5・§6のissuer、audience、JWKS、Google origin、`LINE_LOGIN_CHANNEL_ID`、LIFF ID・endpoint、CORSを環境内で照合 |

HTTP Providerはprocess全体で1つ。HTTP未設定時は現行コードがCurrent DBへfallbackするため、
本番12テーブルでは未設定のまま起動しない。Current DB用tablesの追加やHTTP/Current DBの組織別混在で補わない。
migak向けGoogle ID tokenのaudienceと実行サービスアカウントの権限も手動確認する。
`NEXT_PUBLIC_*`はbuild時固定のため、Admin / LIFF Frontendを環境別にbuildし、DB資格情報やBearerを渡さない。

Webhookは既存`POST /line/webhook/{service_id}`を使用する。対象環境の有効service行と
実際に署名するMessagingチャネルのSecretを`services.line_messaging_channel_secret`へ安全に登録する。
`X-Line-Signature`はraw bodyのHMAC-SHA256をbase64化して比較する既存方式を維持する。
DBのnullable Login ID / LIFF URL / Messaging access tokenはcanonical設定mapの代用品ではない。
canonical Loginはprocess設定、送信tokenとdeep linkはorganization/service別mapで解決する。
複数service利用時は、各Webhook URLとチャネルの配送先対応をLINE管理者が確定する。同一チャネルで任意の複数URLへ配送できると仮定しない。
**本番Webhook URL・チャネル切替、service有効化は手動承認後のみ**。今回は開発チャネルとWebhook URLを変更しない。
現行Webhookは署名検証・event種別のログ・応答までで、canonical連携を作成・解除しない。
新本番DBのLINE連携は空から始め、LIFF経由で組織ごとに新規登録する。

### 構築後の読取り確認とruntime起動前Gate

- [ ] 対象schemaの12テーブル、全列・型・NULL/default・PK・FK・unique・index、必要sequenceをmetadataと照合する。
  appsのapi_key_id unique、servicesのapp FKと`idx_services_app_id`、canonicalの複合uniqueを含める。
  不一致をprovisionerの再実行だけで解決しない。CLI成功・SQLite test成功を実PostgreSQLの検証済みとしない。
- [ ] 許可したStaff / permission / apps / services以外の初期行がないことを、件数・非機密識別子で確認する。
  通知5テーブルとLINE3テーブルは空、旧scopeの行・権限はゼロであることを確認する。Secret列・LINE subject・snapshot本文を証跡へ出さない。
- [ ] 設定変更先が本番だけであること、開発DBと開発runtimeが従来接続を維持すること、両BackendのDB・内部API・scopeが環境内で一致することを再照合する。
- [ ] **Adminは起動時にrunnerを開始する。** 空の本番Outbox/Operationを確認し、旧pendingのあるDBへ誤接続していないことを確認してから起動を承認する。
  既存環境の稼働runner・未完了通知も人間が棚卸しする。scope変更で旧Outboxを新組織へ読み替えない。
- [ ] **LINE標準startupはrecoveryを開始しない。** 通常のCommand受付はrequest内で配信処理を行う。
  Recoveryは`POST /internal/v1/notification-commands:recover`の認証付きone-shot呼出しで動く。
  外部Scheduler等の有無・接続先・稼働中requestを確認し、許可前に起動しない。既存Bearer認証をOIDCだけで代用しない。
  scopeは保存済みorganization/serviceの組で検査され、recovery取得は許可scope絞込み後に件数制限される。
- [ ] `APP_ENV=production`ではLINE production senderを使い、local送信許可・prefix・人数設定を安全停止に利用できない。
  旧Command・snapshotをコピーせず、実送信先・チャネル・起動条件の承認までは通知受付とrecoveryを公開しない。
- [ ] DB構築完了後も、§7の認証・scope拒否・Staff権限・HTTP Provider・Webhook署名・LIFF連携・限定送信の各疎通確認は別のManual Gateとする。
  scope認可の確認は、連携解除後の保存済みsnapshot再送停止を保証するものではない。

## 1. Before deployment — 前提と停止条件

- [ ] 検証対象のProviderを確定する。開発Current DB baselineと、冒頭の本番HTTP Provider / 12テーブル構築を区別する。
- [ ] `ADMIN_EXTERNAL_BUSINESS_BASE_URL`設定時は`HttpExternalBusinessGateway`、未設定時は`CurrentDbExternalBusinessGateway`を使用する。本番12テーブルではHTTP設定を必須とする。
- [ ] 4 unitの対象環境、DB、service / organization / center、runner ownership、配備担当者、停止時間、復旧責任者を確定する。
- [ ] Actual envは人間が設定し、secretはSecret Manager等で管理する。値、ID Token、Authorization、DB接続文字列を文書・build args・ログに残さない。
- [ ] 本文の実DB・HTTP・認証・cloud確認はすべて§7のManual Gateとして実施する。実装中のVerificationはcode review、focused tests、mocks、static review、artifact確認のみ。
- [ ] 旧新版workerを同時稼働させない。HTTP trafficを0にするだけではworker停止を証明できない。
- [ ] Migration前に新runtimeを起動しない。Admin startupはrunner activationであり、UI公開前でも既存通知を再処理し得る。LINEはrequest内処理と認証付きone-shot recoveryを使う。
- [ ] 起動前に既存Admin outbox / LINE command / provider deliveryの未完了処理を棚卸しし、再開対象と送信影響を承認する。UIの送信ボタンを触らないことは送信停止の保証にならない。
- [ ] 既存queueを安全に扱えない場合は起動を停止する。送信disabledへの変更をworker pauseとして使わない（処理結果を変える可能性がある）。

### Safe Deployment Order

1. Deployment scope、URL計画、送信範囲・停止条件を確定。
2. 対象DBのbackupとrestore手順・復旧点を確認。
3. 新規操作受付を止め、旧Admin / LINE workersを停止。停止後の残処理とbackupとの差分を確定し、必要なら停止状態のbackupを追加。
4. 対象Providerとowned schemaの現状・権限を確認。空の本番DBでは冒頭の12テーブル手順を使用。
5. Admin通知・LINE persistence・Webhookの専用provisioningを適用・確認。
6. Staff schema / identity / permissionを準備・確認。
7. Runtime config / secrets、接続先URL、起動直後の処理安全性を確認。
8. LINE Backendを起動。
9. LINE URL確定後、Admin Backendを起動。
10. 双方向Internal APIを確認。
11. Backend URLsを確定し、public設定を与えて両Frontend imageをbuild。LINE / LIFF Frontendを配備。
12. Admin Frontendを配備。
13. Frontend URLsに合わせてBackend CORS、LIFF endpoint、Google Origin、deep linkを整合。
14. Deployment-Precheck Manual Gateを完了。
15. 明示承認したtest memberへの限定実LINE送信とE2E / recovery確認。
16. 証跡をまとめ選択したProviderでの統合動作の合否を判定。不合格なら公開を停止。

LINEはAdmin URLも必要とする。手順7で安定したAdmin宛先を人間が確定する。
新規serviceでURLが未確定ならURL確定方法を先に解決し、架空URLで疎通完了扱いにしない。
URLを得るためにmigration前のapplication起動を行わない。LINE起動時にAdminがまだ稼働していない区間は、canonical LIFF業務を公開せず、双方向確認を手順10まで保留する。

## 2. Migration — 旧worker停止後、新runtime起動前

### Backup / worker stop

- [ ] §7 DB gateで対象DBとbackupの復旧可能性を確認する。Runtime DB権限とmigration権限を区別する。
- [ ] 旧Admin worker全instance / revision / 別processを停止し、lease / claim token fencing非対応workerの書込みがないことを確認。
- [ ] 旧LINE workerも停止し、`request_snapshot`非対応workerが新しいsnapshotなしattemptを作らないことを確認。
- [ ] HTTP traffic、minimum instances、revision tag、別worker起動元を含め、旧processが残っていないことを確認。停止の確認が取れなければmigrationへ進まない。

### Schema ownershipと適用対象

| 区分 | 対象・正本 | 後続作業 |
| --- | --- | --- |
| Current DB business | [Current DB adapter](../backend/app/adapter/current_db_external_business.py)の`public` tables | SELECT専用。今回のprovisioning対象にしない |
| Admin通知 | [admin_tables.py](../backend/app/db/admin_tables.py) | operations / targets / deliveries / audit_events / outboxの5 tables |
| LINE canonical | [LINE tables.py](../../silver-line-repo/backend/app/db/tables.py)のowned 3 tables | `line_recipient_linkages` / `line_notification_commands` / `line_provider_deliveries` |
| Staff | Admin `admin_tables.py`と[Staff repository](../backend/app/db/staff_identity_repository.py) | `staff_identities` / `staff_service_permissions`を別途準備 |
| LINE Webhook | LINE `tables.py`の既存定義 | `apps` → `services`をWebhook専用provisionerで準備。初期行は手動 |

- [ ] Adminは既存[provision_admin_notification_tables.py](../backend/scripts/provision_admin_notification_tables.py)を承認済み環境で使用する。[provisioning module](../backend/app/db/admin_notification_provisioning.py)が5 tablesを`checkfirst`で作成し、outboxへnullable `lease_expires_at` / `claim_token`を追加する。
- [ ] LINEは既存[provision_line_persistence_tables.py](../../silver-line-repo/backend/scripts/provision_line_persistence_tables.py)を使用する。[provisioning module](../../silver-line-repo/backend/app/db/line_persistence_provisioning.py)がowned 3 tablesを作成し、provider deliveryへnullable JSON `request_snapshot`、commandへnullable日時`terminal_at`を追加する。
- [ ] 両scriptはそれぞれowner SettingsのDBを使用する。実行先・対象revisionを人間が確認してから適用する。Backend Dockerfileは`app`のみCOPYするため、これらscriptを通常runtime image内で実行できる前提にしない。承認したsource checkout / migration作業環境を使う。
- [ ] `checkfirst`は既存tableの任意のschema差分を修復する仕組みではない。列・型・index・constraint差分があれば停止し、DB担当者が適用計画を確定する。共有metadata全体の`create_all`でbusiness / legacy tablesを作らない。
- [ ] Staff tablesは通知provisioningに含まれない。専用Staff preparationを下記Slice 3.3手順で実施し、schemaを確認する。起動時に自動作成されると扱わない。
- [ ] Staff identityはUUID形式の`staff_id`、`identity_provider`=OIDC issuer、`external_subject`=検証済みsubject、active状態を設定。emailによる自動登録・照合ではない。serviceごとのroleは`viewer` / `sender` / `admin`を確認（既存`operator`は読取り時`sender`に正規化）。
- [ ] §7 DB gateがすべて合格するまで新Backendを起動しない。既存command ID、idempotency key、payloadを再生成しない。過去snapshotはbackfillしない。

### Slice 3.2 — provisioningの保証範囲と実行時注意

コード上の確認であり、実DB適用済みという意味ではない。
Adminはnullable `lease_expires_at`（PostgreSQLではTIMESTAMP WITH TIME ZONE、test SQLiteではDATETIME）とnullable TEXT `claim_token`、
LINEはnullable JSON `request_snapshot`とtimezone付きnullable日時`terminal_at`を不足時だけ追加する。Table定義と一致する。
各専用provisionerはtable作成の後に追加列migrationを呼ぶ。逐次再実行では既存table / columnを再作成しない。
DROP / DELETE / ID再採番 / command・idempotency key再生成 / payload・snapshot backfillは行わない。
これは任意の旧schemaを修復する保証ではなく、現在の基礎schemaに上記追加列だけが欠けた状態を対象とする。

| Owner table | PK / 主なunique・FK・index（完全な列定義は上記metadata参照） |
| --- | --- |
| admin_notification_operations | operation_id PK、service_id / created_at index |
| admin_notification_targets | operation_id + member_id PK、operation FK |
| admin_notification_deliveries | delivery_id PK、operation FK、operation_id / created_at index |
| admin_notification_audit_events | audit_id PK、operation FK、operation_id / created_at index |
| admin_notification_outbox | outbox_id PK、command_id / idempotency_key各unique、operation_id + target_id unique、operation FK、state / created_at index |
| line_recipient_linkages | id PK、organization + service + member / subject各unique、business identity検索index |
| line_notification_commands | command_id PK、idempotency_key unique、operation index、status / accepted_at index |
| line_provider_deliveries | delivery_id PK、command FK、command_id + attempt_number uniqueとindex |

Adminのnew claimは60秒leaseと新claim tokenを設定する。有効leaseは取得せず、期限切れ / legacy NULL leaseは同じcommandをreclaimできる。
旧tokenのoutcome更新はno-op。Accepted / terminalを新規送信claimに戻さない。
LINEのnew attemptはrecipientと順序付きmessagesのsnapshotを保存し、credentialを含めない。
同じcommand / attemptのretry keyとpersisted bodyでreplayし、terminalは再送対象外。
Legacy NULL / 不正snapshotは現在設定から再生成せず、provider callなしでUNKNOWNへ収束する。
このためadditiveでも旧新版の混在は安全とみなさず、旧worker停止 → migration → 新runtimeの順序を維持する。

Scriptはowner Settingsをimportするため、実行時はprocess envから実DB設定を読む。APP_ENV=localを明示した場合のみowner dotenvも使用可能。productionはdotenvを読まない。
本Sliceではscriptを実行せず、helperをtest-only DBで検証する。実行時は`engine.begin()`のtransaction内で処理し、finallyでengineをdisposeする。
失敗は握り潰さず非zero終了し、成功時だけtable名を出力する。DDL識別子は固定でuser inputを埋め込まない。
NOTE: 既存通知 / canonical persistence CLIは未処理例外のtracebackをsanitizeする境界を持たない。設定validation / driver例外に機密が含まれない保証はないため、
Manual Gateではstderr・作業ログを機密として扱い、生の出力を共有しない。明示的なsecret / DATABASE_URLログ出力はない。
全列型・index・FK・constraintの自動修復、同時migration実行の排他は保証しない。人間が単独実行し、§7で実schemaと既存row保持を確認する。
Staff / Current DB business / LINE legacy tablesは対象に含めない。

### Slice 3.3 — Staff Preparation（実行はManual Gateのみ）

正本は[Staff metadata](../backend/app/db/admin_tables.py)と[repository](../backend/app/db/staff_identity_repository.py)。

| Table | Code-level schema |
| --- | --- |
| staff_identities | staff_id Text PK、identity_provider / external_subject Text NOT NULL、email / display_name nullable Text、active Boolean NOT NULL（server default true）。issuer + subjectにunique、追加の明示indexなし |
| staff_service_permissions | staff_id / service_id Textの複合PK、role Text NOT NULL。staff_idはidentityへのFK（ON DELETE CASCADE）、service_idにindex |

staff_idはDB型がTextでもrepositoryがUUIDとしてparseするためUUID文字列を保存する。
DBのText型にはrole enumやUUIDの検証機能はない。既存値の型・制約・nullable・roleのdriftはManual Gateで照合し、自動修復しない。

- [ ] 承認したbackend source作業環境で`python scripts/provision_admin_staff_tables.py`を実行する。
  [専用helper](../backend/app/db/admin_staff_provisioning.py)はidentity → permissionの順で2 tablesのみcheckfirst作成する。
  既存tables / rowsをresetせず、通知・business・LINE tablesを作らない。Staff登録は別操作。
- [ ] 実Google loginの検証済みID Token claimsからissuer / subを安全に確認し、登録対象・service・roleの承認を得る。
  Tokenそのものをログ・文書・登録入力に保存しない。Googleの想定issuerは`https://accounts.google.com`。
  既存OIDC validatorは設定issuerの末尾`/`を除去し、authenticatorも検証後issの末尾`/`を除いてlookupする。
  登録identity_providerはそのlookup文字列にexact matchさせる。subはそのまま。新CLI / repositoryでaliasや正規化を追加しない。
  CLIは末尾`/`付きissuerをDB接続前に拒否する。`https://accounts.google.com/`ではなくcanonicalな`https://accounts.google.com`を入力する。
- [ ] `python scripts/register_admin_staff.py`へ承認済みJSON objectを標準入力で1件渡す。PIIをcommand-line引数やshell履歴へ直接貼らず、管理された入力経路を使う。
  必須はstaff_id（UUID）、identity_provider（issuer）、external_subject（sub）、active（JSON boolean）、service_id、role。
  email / display_nameは任意の文字列またはnull。省略時nullになり、再登録でも既存値をnullへ更新するため保持したい値は明示する。
  不明fieldは拒否し、token / password / OAuth secretは受け取らない。
- [ ] 登録はidentityと指定serviceのpermissionを同じtransactionでupsertする。同じstaff_idのissuer / subject付け替えは禁止。
  同じissuer / subjectを別staff_idへ登録するとunique制約で失敗し、部分登録しない。
  同じstaff + serviceの再登録はrole更新。他serviceのpermissionは保持する。
  active=falseも同じ入力で指定可能で、既存Google accountを停止できない場合でもStaffアクセスを拒否する。
- [ ] Canonical保存roleはviewer / sender / admin。旧DB値operatorはrepositoryでsenderへ互換変換するが、新CLIはoperatorを受け付けない。
  Viewerはread、senderは通常write / send、adminはそれらとadmin専用操作を許可。
  Frontendの環境別表示制限をBackend認可と同一視しない。
- [ ] X-Service-IDは要求serviceで、DB permissionを付与しない。指定時は一致するpermissionが必須。
  省略時はpermissionがちょうど1件の場合のみ採用し、0件・複数件は拒否する。
- [ ] Workspace / personal Gmailとも登録済みissuer + sub、active、permissionで判定する。
  email / display_name / hd / domainはauthorization keyではない。Google login成功だけでStaff自動作成しない。
- [ ] 新CLIは入力をvalidateしてからSettings / DBを初期化する。成功は固定メッセージ、失敗は値を含まない固定メッセージとexit 1。
  Staff table CLIは成功時table名のみ出力する。両scriptは実行時にAdmin Settingsのactual envを使用するため、この実装Sliceでは実行しない。
  登録は単独の承認作業として行う。同時登録の競合はDB制約で失敗し得るので成功を仮定しない。
- [ ] §7で実schema確認 → 専用provisioner → 検証済みissuer/sub確認 → 承認済みStaff / permission登録 → active=trueを確認する。
  Registered read、unknown / inactive / permissionなしの403、viewer writeの403、senderとadminの操作、両Google account種別、logout / reload / expiryを確認する。
  Staff table欠落はDB例外でfail closed（OperationalErrorは503、その他SQLAlchemyErrorは500）。欠落時に自動作成しない。

## 3. Runtime config / secrets

正本はSlice 2.1の[Admin example](../.env.admin.example) / [共通example](../.env.example)、[LINE example](../../silver-line-repo/.env.line.example) / [共通example](../../silver-line-repo/.env.example)。空値・`{}`は完成した設定ではない。Actualファイルを本文へ転記しない。

| Unit | 人間が準備するcanonical設定 |
| --- | --- |
| Admin Backend | `DATABASE_URL`, `APP_ENV`, `ADMIN_INTERNAL_API_BEARER_TOKEN`, `ADMIN_INTERNAL_API_SCOPES`, `ADMIN_EXTERNAL_BUSINESS_BASE_URL`, `ADMIN_EXTERNAL_BUSINESS_AUDIENCE`, `CURRENT_DB_BUSINESS_CENTERS`（Current DB使用時のみ）, `ADMIN_NOTIFICATION_RUNNER_SERVICE_IDS`, `ADMIN_LINE_INTERNAL_API_BASE_URL`, `ADMIN_LINE_INTERNAL_API_BEARER_TOKEN`, `ADMIN_CORS_ALLOWED_ORIGINS` |
| Staff OIDC | `ADMIN_OIDC_ENABLED`, `ADMIN_OIDC_ISSUER`, `ADMIN_OIDC_AUDIENCE`, `ADMIN_OIDC_JWKS_URL`, `ADMIN_OIDC_ALGORITHMS`（`RS256`を空値で上書きしない） |
| LINE Backend | `DATABASE_URL`, `APP_ENV`, `LINE_INTERNAL_API_BEARER_TOKEN`, `LINE_ADMIN_INTERNAL_API_BASE_URL`, `LINE_ADMIN_INTERNAL_API_BEARER_TOKEN`, `LINE_ADMIN_SERVICE_SCOPES`, `LINE_LOGIN_CHANNEL_ID`, `LINE_COMMAND_MESSAGING_ACCESS_TOKENS`, `LINE_CANONICAL_LIFF_ENTRY_BASES`, `LINE_CORS_ALLOWED_ORIGINS` |
| LINE local safety | LINE repositoryの最新local templateを参照。APP_ENV=localとLOCAL_LINE_MAX_RECIPIENTS等を人間が確認 |

- [ ] Adminはlocal / production両方でStaff OIDCを必須とする。Demo認証へのfallbackはない。
- [ ] local統合確認はAdmin / LINEともAPP_ENV=local。productionは両者APP_ENV=production。Frontendのbuild / runtime設定を一致させる。
- [ ] 旧ADMIN_LOCAL_INTEGRATION_MODE / SCOPESは廃止。ADMIN_INTERNAL_API_SCOPESと明示runner ownershipへ統一する。
- [ ] LINEはproduction sender / local安全senderを使う。staging_liveはlocal安全送信の互換wire labelでありruntime環境名ではない。
- [ ] ProductionのS2S URLはHTTPS。SecretやDB接続情報はBackendにのみ供給し、Frontend buildへ渡さない。

### S2S credentialとscope

| 方向 | 送信側 = 受信側 |
| --- | --- |
| Admin → LINE | `ADMIN_LINE_INTERNAL_API_BEARER_TOKEN` = `LINE_INTERNAL_API_BEARER_TOKEN` |
| LINE → Admin | `LINE_ADMIN_INTERNAL_API_BEARER_TOKEN` = `ADMIN_INTERNAL_API_BEARER_TOKEN` |

2組は別credentialで、Staff OIDCとも別。Fallbackや共用はない。

| 設定 | 責務 |
| --- | --- |
| `ADMIN_INTERNAL_API_SCOPES` | service_id → organization_id。Inbound認可とcanonical scopeの解決 |
| `CURRENT_DB_BUSINESS_CENTERS` | organization_id → center_code。Business readの範囲 |
| `ADMIN_NOTIFICATION_RUNNER_SERVICE_IDS` | 明示的なservice ownership。上記Admin scopesに含まれるIDだけを指定。認可scope全件から自動推論しない |
| `LINE_ADMIN_SERVICE_SCOPES` | service_id → organization_id。Canonical LIFF / Admin呼出しのtrusted scope |
| Messaging / deep link maps | organization_id → service_id → token / LIFF entry base。認可scopeやrunner ownershipとは別 |

## 4. LINE Backend → Admin Backend

| Unit | Build context / Dockerfile | Entrypoint |
| --- | --- | --- |
| LINE Backend | `silver-line-repo/backend` / `Dockerfile` | `uvicorn app.main_line:app` |
| Admin Backend | `silver-admin-repo/backend` / `Dockerfile` | `uvicorn app.main_admin:app` |

両DockerfileはPython 3.12、host `0.0.0.0`、port `${PORT:-8080}`。起動時migrationはない。

### LINEを先に起動

- [ ] Migration合格、DB、APP_ENV、incoming bearer、Admin URL / bearer / scopes、Login channel、Messaging map、deep link、local safetyを確認済みにする。
- [ ] [main_line.py](../../silver-line-repo/backend/app/main_line.py)と[app_factory.py](../../silver-line-repo/backend/app/app_factory.py)の標準startupはrecovery pollingを開始しない。通常受付はrequest内処理、recoveryは認証付きone-shot endpoint。外部triggerと実行中requestを管理する。
- [ ] 起動後の`/health`、Internal API / capabilityは§7で確認。Canonical linkage / LINE Login / Admin接続はAdmin起動後に確認し、それまで業務公開しない。

### Adminを次に起動

- [ ] LINEの確定URL、Admin migration、Staff schema、HTTP Provider（Current DBの場合はcenter mapping）、双方向credential、runner ownership、OIDC、CORSを確認済みにする。
- [ ] [main_admin.py](../backend/app/main_admin.py)は明示runner IDsでcanonical compositionを構成する。空ownershipでは通知applicationの完成とはならない。
- [ ] [app_factory.py](../backend/app/app_factory.py)が[AdminNotificationRunner](../backend/app/application/admin_notification_runner.py)をstartupで開始、shutdownでcancel / awaitする。手動GETを通知進行の条件にしない。
- [ ] §7で`/health`、Staff OIDC、Admin Internal API、選択したProviderのbusiness reads、capability、runner、LINE result reconciliationを確認する。`/health`成功だけでDB・認証・runner健全性を合格扱いにしない。

## 5. Frontends — Backend URL確定後にbuild

| Unit | Context / Dockerfile | Target / output | Public build args（APP_ENV以外はNEXT_PUBLIC） |
| --- | --- | --- | --- |
| Admin | `silver-admin-repo/frontend` / [Dockerfile](../frontend/Dockerfile) | `targets/admin` / `.next-admin` | `APP_ENV`, `NEXT_PUBLIC_ADMIN_API_BASE_URL`, `NEXT_PUBLIC_ADMIN_SERVICE_ID`, `NEXT_PUBLIC_GOOGLE_CLIENT_ID` |
| LIFF | `silver-line-repo/frontend` / [Dockerfile](../../silver-line-repo/frontend/Dockerfile) | `targets/line` / `.next-line` | `APP_ENV`, `NEXT_PUBLIC_LINE_API_BASE_URL`, `NEXT_PUBLIC_LIFF_ID` |

- [ ] Node `22-bookworm-slim`、lockfile + `npm ci`、`npm run build`、通常のNext Node serverを使用する。Standalone / exportではない。
- [ ] 起動は両方とも`npm start -- -H 0.0.0.0 -p "${PORT:-8080}"`。Repo rootではなく各frontendをcontextにする。
- [ ] `.dockerignore`によるactual env / credential / node_modules / cache除外を維持する。FrontendにDB・S2S・Messaging secretを渡さない。
- [ ] `NEXT_PUBLIC_*`はbuildへ埋め込まれるため、環境ごとにpublic configを確定してrebuildする。Runtime envだけの変更では切り替わらない。Owner API URLを空にするとgeneric fallbackを抑止する点にも注意する。
- [ ] `APP_ENV`は同一image内のbuild / runtimeで一致させ、配備時に別値へ上書きしない。Google client IDはBackend OIDC audienceと同じWeb client ID。
- [ ] Backend URLs確定後に両imageをbuildし、LINE / LIFF、Adminの順に配備する。相互のFrontend build依存はない。
- [ ] 新health routeは不要。TCP startupと既存public pageを基にprobeを計画する。Admin production rootは未認証時redirectするため、HTTP probeを認証必須pathに依存させない（公開`/auth-required`がある）。LIFFには公開rootがある。

## 6. URL / CORS finalization

- [ ] Backend URL → public build args → Frontend image → Frontend URL → Backend CORS更新 → LIFF endpoint / Google Authorized JavaScript Origin更新、の順で整合させる。
- [ ] Admin / LINE CORSは対応するFrontend originを指定。BrowserのAuthorization、Adminの`X-Service-ID`、必要なmethod / preflightを§7で確認する。
- [ ] LIFF endpoint、`NEXT_PUBLIC_LIFF_ID`、LINE Login channel、scope別canonical deep link、`service_id`を整合。API URLやpublic IDが変わった場合は該当Frontendをrebuildする。
- [ ] Backend config更新で新revisionが起動する場合もrunnerの切替として扱う。旧新版の同時処理を避ける同じ停止・ownership確認を適用する。

## 7. Manual Gate — 実接続確認の集約

ここにある全項目は人間が後続工程で実施する。DB、Cloud Run、Google、LINE、LIFF、IAM、Secret Manager、actual HTTP / token / CORS、Messaging APIへ今回接続しない。
前節はこのgateを実施する順序を示す。Gateは一度に最後へ先送りするものではなく、DBは起動前、疎通は起動後、送信はprecheck合格後に確認する。

### DB gate — 起動前

- [ ] Backup / restore可能性、対象DB、migration権限・runtime権限、各ownerの接続先を確認。Current DB使用時のみAdminは同じ`DATABASE_URL`でowned persistenceとbusiness readsを扱う。本番HTTP Providerの業務正本は外部APIである。
- [ ] Admin通知5 tables、outboxの`lease_expires_at` / `claim_token`、command_id / idempotency_keyのunique、operation-target unique、FK / indexをmetadataと照合。
- [ ] LINE canonical 3 tables、`request_snapshot`、linkageのorganization-service-member / subject unique、command idempotency unique、delivery command-attempt unique、FK / indexを照合。
- [ ] Staff両tables、UUID形式staff_id、issuer / subject unique、active、service / role、FK / indexを照合。DBのText型だけではUUID形式を保証しない。
- [ ] 以下Current DB 4項目は開発Current DB利用時だけ適用し、本番12テーブルでは冒頭のHTTP Provider gateへ置き換える。
- [ ] Current DB `public.members`: `id`, `member_code`, `full_name`, `center_code`。
- [ ] Current DB `public.jobs`: `id`, `job_code`, `title`, `summary`, `location_text`, `work_date_text`, `status`, `updated_at`, `center_code`。
- [ ] Current DB `public.job_recommendation_flags`: `member_id`, `job_id`, `center_code`, `is_recommended`。
- [ ] ID / join列のUUID、`updated_at`のtimezone、recommendation flag、organization-center mappingの一致を確認。Business tablesはread-onlyで、owned migrationで変更しない。
- [ ] 既存未完了rows、legacy NULL lease / snapshot、処理再開の影響を記録。Snapshot不明の過去attemptを現在configから作り直さない。

### Deployment-Precheck — 限定送信前

- [ ] **Cloud Run / image**: Node 22 Linuxで両Frontend image build / start、4 unitのPORT、instance lifecycle、shutdown、request外CPU、minimum instances、max instances、DB connection limits、時刻同期を確認。数値は担当者が負荷・DB枠に基づき決定し、本文では固定しない。
- [ ] **Background CPU**: runnerはHTTP request外でも動くため、そのCPU実行条件が必要。Trafficがない状態での稼働、scale-to-zeroと復旧の影響、multiple instances時のownershipを確認。Cloud Run設定はPhase 4 / Manual Gateで行う。
- [ ] **IAM / secrets**: runtimeが必要なsecretへアクセス可能で、Frontendへの混入・request body / tokenのログ出力がないことを確認。Cloud Run側の認証を使う場合、現在のclientが送るapplication bearerとの整合を確認し、Google IAM ID tokenの自動付与があると仮定しない。
- [ ] **Admin↔LINE**: 正しいcredentialで双方向HTTPを確認。欠落・誤credentialと不正scopeが拒否されることを確認。LINE→Adminの会員検証 / summary / recommended jobs / detail、Admin→LINEのrecipient照会 / result / capabilityを確認。Command送信は次の限定E2Eまで行わない。
- [ ] **Google Staff Auth**: Google Web OAuth Client、Audience External、Authorized JavaScript Origin、public client IDと`ADMIN_OIDC_AUDIENCE`の一致、issuer、JWKS、algorithmsを確認。Google Consoleでの実確認はこのgateのみ。
- [ ] **Staff認可**: Workspace account / personal Gmailのregistered Staffが利用可能、unregistered Staffは403、inactive Staffは403、viewerのwrite拒否、service越境拒否を確認。GISのID TokenはBackendで検証し、認可はStaff DBで決定する。
- [ ] **Staff session**: logout、reload時のsessionStorage復元、token expiry / 401での再認証を確認。Cookieはrouting hintであり認証credentialではない。Static Bearerを代替にしない。
- [ ] **LIFF / LINE Login**: LIFF ID / endpoint / `LINE_LOGIN_CHANNEL_ID`、explicit `service_id` context、ID Token検証、member verification、unique match時のcanonical linkage、reload、recommended jobs、job detail、deep linkを確認。`line_member_links`や固定memberへのfallbackで成功扱いにしない。
- [ ] **CORS / URL**: §6のURL整合、実browser preflight・API応答、公開page / probeを確認。
- [ ] **Send capability**: LINE `POST /internal/v1/send-capability:check`とAdmin `GET /admin/line-send-mode`を照合。`disabled` / `staging_live` / `production_live`、Admin側の取得失敗`unavailable`、ready true / false、blocking reasons、max_recipientsを確認。Live modeでもready=falseは送信不可。旧`fake`表示を現在canonical runtimeの判定に使わない。
- [ ] **三段階の送信制限**: Admin UI表示・button、予約直前のBackend guard、LINE sender最終制限を確認。Stagingでは許可test member 1名、`max_recipients=1`、非空prefix、allowlist、scope別token / deep linkが必要。Capability成功だけでは外部provider疎通を証明しない。
- [ ] 上記不合格があれば実送信へ進まない。Mode切替や否定ケースの確認は承認した隔離範囲で行い、稼働queueのconfigを不用意に変更しない。

### 限定LINE Messaging / Notification E2E — precheck後

送信先test memberと時刻を人間が承認し、下記順序を実環境の証跡で確認する。コード上のstate定義の再確認ではなく、実際の永続化・HTTP・provider・収束が確認対象。

1. [ ] Admin求人一覧（0件 / 件数 / pagination / scopeを含む）。
2. [ ] Job detail。
3. [ ] Candidate。
4. [ ] Operation create。
5. [ ] Target select（承認された対象のみ）。
6. [ ] Message edit。
7. [ ] Validation。
8. [ ] Send capabilityとready / recipient limit。
9. [ ] 限定send、prefixと実端末受信。
10. [ ] Admin Outbox永続化とcommand identity。
11. [ ] LINE command永続化 / acceptance。
12. [ ] Provider deliveryとpersisted request_snapshot（内容・宛先は機密として扱う）。
13. [ ] LINE result。
14. [ ] Admin reconcile。
15. [ ] Delivery terminal。
16. [ ] Operation terminal（全SENTならCOMPLETED、error等を含めばCOMPLETED_WITH_ERRORS、pending中はSENDING）。
17. [ ] `completed_at`の初回確定と重複reconcileでの維持。

### Recovery / baseline判定

- [ ] Admin process restart、stale lease reclaim、旧claim tokenでのoutcome write拒否を実DBで確認。同じlogical command / payloadを保つ。
- [ ] LINE process restart後、承認したone-shot recoveryを呼び、persisted snapshotと同じretry key / bodyの再利用、terminal exclusionを確認。再起動だけではrecoveryしない。Provider受理済み409はaccepted request ID付きか区別する。
- [ ] 期限切れ / 不正・欠落snapshotはUNKNOWNへ収束し、blind resendされないことを確認。現在のretry windowは24時間から30秒marginを引いた範囲。UNKNOWNは未送達の証明ではない。
- [ ] Cloud Run instance restart / multiple instancesでrow lock・lease・重複効果抑止を確認。HTTPが常に1回だけになると期待しない。障害注入は承認された検証範囲で行う。
- [ ] Precheck、限定E2E、recoveryの証跡が揃った場合のみ対象Providerでのbaseline合格とする。未実施・不合格は公開判定を保留。

## 8. Rollback / stop condition

- Migration前: 作業中止可能。ただし旧worker再開はqueueと停止理由を確認して承認する。
- Migration後・新app起動前: 旧appを勝手に再起動しない。Schema compatibilityとsnapshot / fencing対応を確認し、復旧責任者がrestoreまたは対応版を選ぶ。
- 新app起動後: まず受付とworker ownership / 全instanceを確認して停止する。単純traffic rollbackではbackground runnerは止まらない。
- 外部送信後: DB restoreは送信を取り消さない。Provider結果、command / retry identity、未確定attemptを照合し、同じ通知を新commandとして再送しない。
- Schema差分、旧worker残存、scope不一致、secret/認証/CORS不備、capability不整合、未承認宛先、収束不明があれば停止し、人間が原因と再開条件を確定する。自動rollback scriptは本Sliceで作らない。

## 9. External company PR境界と参照

HTTP Providerは実装済みで、設定により選択する。外部会社APIへの実接続は別Manual Gateであり、
本番12テーブルはこのProviderを前提とする。Current DB baselineの結果だけでHTTPの疎通を保証しない。
Admin / LINE / Auth / runner問題とexternal provider問題を区別する。

詳細は[Phase 5 verification](PHASE5_END_VERIFICATION.md)、[Admin recovery](PHASE5_SLICE53_STATE_RECOVERY.md)、[LINE recovery](../../silver-line-repo/docs/LINE_COMMAND_RECOVERY.md)、[canonical linkage](../../silver-line-repo/docs/CANONICAL_MEMBER_LINKAGE.md)を参照。
これら過去文書のPhase番号は当時のロードマップのもの。旧send-mode表示やFrontend未対応という履歴記述より、現在sourceと本RunbookのPhase 1 / Slice 2.1–2.2 contractを優先する。
Cross-repositoryリンクは両repositoryを同じ親directoryへ置く前提。本Sliceは文書作成のみで、実配備・実接続・migration・Phase 3着手を実施していない。

## Admin二環境化の配備境界

APP_ENVはprocess envでlocal / productionを明示し、旧値・未設定を拒否する。productionはCloud process env / Secretのみで、repositoryの.env.adminを読み込まない。DB/OIDC/LINE URL・Bearer/canonical scopes/runner ownershipの不足はstartupで拒否する。外部業務APIが未設定ならCurrent DBを使い、Fakeへfallbackしない。

Frontendはnpm run build / npm startのlauncher経由とする（VercelのBuild Commandもnpm run build）。Next標準dotenvはtarget directoryに配置せず、読込み前に検査で拒否する。NEXT_PUBLIC_ADMIN_API_BASE_URLは非空必須、空をsame-originとは扱わない。NEXT_PUBLIC_GOOGLE_CLIENT_IDも必須。公開envはbuild-time固定であり、runtime変更でretargetできない。APP_ENV/公開設定をbuildとstartで揃え、変更時は再buildする。Backend secretをbuild args / NEXT_PUBLICへ渡さない。

local標準はFrontend 3001、Backend 8082、Python 3.12 / Windows SelectorEventLoop。実Google Staff Login、開発DB、Current DB、https://silver-backend.ngrok.app経由のLocal LINEを使う。Admin用ngrokは必須ではなく、LINE -> Admin逆方向の外部到達性が必要な場合だけ人間が準備する。localhostと127.0.0.1は別originとしてGoogle/CORS登録する。

localはselected 10人まで。11 selected / 10 sendableもBackendがDelivery/Outbox生成前に拒否する。productionには固定上限を適用しない。LINE ready/capability上限は両環境で維持する。staging_live、旧staging-readiness、送信Internal API contractは変更しない。

Manual Gate: 人間による実env、Google Origin、Staff identity/permission、開発DB・未完了Operation確認、Admin/LINE/Frontend起動、Google Login、1人/複数人/10人/11人境界、sender icon表示、production DB/LINE URLと双方向credentialの環境対応、Cloud env/Secret設定、deployment。runnerは未完了送信を再開するため、起動前に接続DBと所有scopeを確認する。

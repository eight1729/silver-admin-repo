# External Business Integration Requirements — Slice 1.1

## Canonical boundary

Admin の `backend/app/domain/ports/external_business.py` にある
`ExternalBusinessGateway` を Application の共通窓口とする。モデルの正本は
`backend/app/domain/models/external_business.py`、結果区分は
`backend/app/domain/enums/enums.py`、障害は `backend/app/domain/errors/errors.py`。
各メソッドは async、引数は keyword-only、既存の external organization scope を使う。
外部情報の正本は External Business。DB / API のどちらでも Adapter がこの契約に変換する。
接続方式、外部 schema、認証、ネットワーク、移行方式は本書では定めない。

## Required business capabilities

| Capability | Input (organization scope 内) | Response semantics |
| --- | --- | --- |
| `verify_member` | `MemberVerificationInput(member_number, name)` | `MemberVerificationResult`。`NO_MATCH` は0件、`UNIQUE_MATCH` は1件、`MULTIPLE_MATCH` は複数件。1件の場合だけ必須の `external_member_id` を返す。それ以外は ID を返さない。 |
| `get_member_summary` | `external_member_id` | 同じ ID の `ExternalMemberSummary(external_member_id, display_label)`。存在しなければ `ExternalMemberNotFoundError`。 |
| `list_recommended_jobs` | `external_member_id` | 既存の `list[ExternalJobSummary]` が正本。会員に対する推薦求人を返す。新しい求人 projection は作らない。 |
| `get_job_detail` | `external_job_id` | 既存の `ExternalJobDetail` が正本。対象求人の詳細を返す。 |

本人照合は会員番号と氏名の組合せを使い、曖昧一致・部分一致・独自 normalization
（漢字・カナ・スペース・大小文字等の変換）は導入しない。入力値を勝手に加工しない。
`check_link_eligibility` の連携可否判定や、求人ごとの `CandidateMember` とは別の責務である。
本人照合成功だけで連携可否を判定しない。

Provider / system failure は既存の `ExternalBusinessError` 系例外で表す。
例えば利用不能は `ExternalSystemUnavailableError`、未設定は
`ExternalBusinessNotConfiguredError`。本人照合の0件・複数件へ障害を丸めない。
Summary の不存在とシステム障害も区別する。

Summary は会員 master 全体ではない。表示属性は既存 `CandidateMember.display_label`
と同じ意味の任意ラベルだけとする。候補資格・推薦順位・LINE identity は含めない。
LIFF の最終表示項目は Admin Repository 内だけでは確定できないため未確認。
生年月日・住所・電話等の属性を推測追加しない。

## Identifier semantics

- `external_member_id`: External Business の organization scope 内で会員を安定して
  識別する ID。会員番号と同一とは限らず、LINE subject ではない。
- `member_number`: 本人照合入力となる業務上の会員番号。`external_member_id` の
  代用品にしない。unique match の ID は Provider が正本から取得する。
- `name`: 会員番号と組み合わせる本人照合入力。表示ラベルとの同一性は契約しない。
- `job_id`: External Business の求人 ID。Gateway / 求人モデルでは既存の
  `external_job_id` がこの意味を持つ。既存の Application の対応を維持する。
- `job_version` 相当: `ExternalJobSummary.version` / `ExternalJobDetail.version`
  が既存の正本。`expected_job_version` と `NotificationValidationResult.current_job_version`
  はその更新判定に使う。既存 Application と同様に文字列の等値で変更を判定し、
  数値順序や日時形式を仮定しない。外部の実際の形式は未確認であり推測しない。

organization / service の意味は既存 `ExternalBusinessGateway` の docstring、
`OrganizationServiceScopeResolver` と `ServiceOrganizationScope` を維持する。
この Slice では scope の再定義・解決処理の変更を行わない。

## Implementation scope and open items

この Slice は domain / provider contract のみ。HTTP API、DB Adapter、接続・schema
mapping は追加しない。既存の検索・候補者・通知対象検証契約も維持する。
既存 Fake / scoped Fake / staging wrapper の追加メソッドは未設定例外を返す
互換対応だけであり、照合・Summary の実装や fixture 拡張は行わない。
実 Provider の安定 ID、照合結果の区別、最終表示項目、求人 revision の対応は
外部仕様を取得した後に確認する。

既存 `CandidateMember.line_subject` は今回以前から存在する。
今回の新規会員契約には含めず、既存モデルの整理もこの Slice では行わない。

## Admin Internal API — Slice 1.2

Admin が provider owner となる server-to-server API。browser 向け認証やスタッフ
OIDC は使用しない。契約正本と互換性規則は
[`backend/contracts/README.md`](../backend/contracts/README.md)、配布物は
`backend/contracts/admin-internal-api-v1.openapi.json`。

すべて JSON body を受け取る POST とする。会員番号・氏名・会員 ID を URL の
path / query に置かず、通常のアクセスログに含めないための選択である。

| Endpoint | Request fields | 200 response |
| --- | --- | --- |
| `/internal/v1/members:verify` | `service_id`, `member_number`, `name` | `status` が `no_match` / `unique_match` / `multiple_match`。`unique_match` だけ必須の `external_member_id` を持ち、それ以外ではキー自体を返さない。 |
| `/internal/v1/members:summary` | `service_id`, `external_member_id` | `ExternalMemberSummary`: ID と nullable な `display_label` のみ。 |
| `/internal/v1/members:recommended-jobs` | `service_id`, `external_member_id` | 既存 `ExternalJobSummary` の配列。推薦がなければ空配列。 |
| `/internal/v1/jobs:detail` | `service_id`, `external_job_id` | 既存 `ExternalJobDetail`。 |

未定義の request field は拒否する。`organization_id` や `line_subject` は入力できない。
本人照合入力は加工せず domain input に渡す。HTTP の3結果は Slice 1.1 の結果を
投影するもので、別の照合方式ではない。求人の domain model は再利用する。

### Authentication and trusted scope

人間が設定する環境変数名:

- `ADMIN_INTERNAL_API_BEARER_TOKEN`: LINE → Admin 専用の incoming credential。
  `ADMIN_LINE_INTERNAL_API_BEARER_TOKEN`（逆方向）やスタッフ OIDC credential と
  別に発行・設定する。fallback / 共用はしない。
- `ADMIN_INTERNAL_API_SCOPES`: この credential の consumer に許可する service ID →
  organization ID の JSON object。信頼する運用設定から登録する。

未設定・空・Bearer token として不正な認証設定は503。credential 不一致・欠落は401。
定数時間比較を使用し、認証の後に業務アクセスを行う。ローカル環境でも認証を省略しない。
この v1 credential は上記 mapping に登録した service 全体へのアクセスを許可する。
consumer ごとの複数 credential / 個別 ACL は今回実装しない。

`service_id` は caller が選択できるが、organization ownership は既存
`ConfiguredOrganizationServiceScopeResolver` が設定から決定する。未知・未許可の
service、不正な設定、不整合な解決結果は fail closed。organization / service の
既存の意味を変えない。mapping に不要な service を登録しないことは運用上の責任となる。

### Errors and PII

既存 Admin と同じ `{"detail": {"error": "..."}}` 形式を使う。

| HTTP | error | Meaning |
| --- | --- | --- |
| 401 | `authentication_failed` | Bearer 欠落・不一致。`WWW-Authenticate: Bearer` を返す。 |
| 403 | `scope_forbidden` | scope が未許可・解決不能・不整合。 |
| 404 | `resource_not_found` | 会員または求人が存在しない。 |
| 422 | `invalid_request` | JSON / request validation 失敗。入力値や詳細を返さない。 |
| 503 | `authentication_unavailable` | 専用認証設定が利用不能。 |
| 503 | `external_system_unavailable` | Provider 未配線・未設定・障害、タイムアウト、response 検証失敗等。 |
| 500 | `internal_error` | 想定外の server failure。 |

no match / multiple match は200の業務結果であり、障害をこの結果に変換しない。
通信自体の失敗は HTTP response を得られない transport failure として consumer が扱う。
例外メッセージ・入力値・Provider response body を応答やログへ出さない。
既存 shared middleware に request body logging はない。新規 route のエラー境界は
入力検証と応答検証を含めて固定エラーへ変換し、新規ログ出力を行わない。
実際の proxy / APM 等が body・Authorization を採取しないことはデプロイ時に確認する。

### Provider wiring and remaining notes

`create_admin_app(..., external_business_gateway=...)` で Gateway 実装を明示注入できる。
Slice 1.3 では未注入時に下記 Current DB Adapter を解決する。Internal API は
local integration の Fake を継承しない。必要な設定がない場合は503となる。
既存 Fake の会員2機能は Slice 1.1 の未設定例外のままである。
Summary の最終表示項目と既存 `CandidateMember.line_subject` は前節の NOTE を維持する。

## Current DB Schema Gate — Phase 3 / Slice 3.1

以下は **code-level expected schema**。現在の
[CurrentDbExternalBusinessGateway](../backend/app/adapter/current_db_external_business.py)
を正本とする。実DBの観測・確認結果ではない。過去の記録にあった「人間確認済み」の
PK / UNIQUE / FK / trigger / データ整合性も、今回の配備先では未検証としてManual Gateで再確認する。
この取り決めはCurrent DB専用で、将来のProduction providerのschemaやID形式を規定しない。
前節のSlice 1.1–1.2は導入時の履歴。現在は検索・候補者検索・通知対象検証も実装済み。

### Expected tables / columns / types

SQLAlchemyの参照用table clauseはすべてschema `public`。
以下の型はコードが期待する型であり、実DBのDDL・nullability・constraintを観測したものではない。

| Table | Column | Code expects |
| --- | --- | --- |
| public.members | id | UUID（Uuid） |
| public.members | member_code, full_name, center_code | Text |
| public.jobs | id | UUID（Uuid） |
| public.jobs | job_code, title, summary, location_text, work_date_text, status, center_code | Text |
| public.jobs | updated_at | DateTime(timezone=True)。読取り結果は非NULLのtimezone-aware datetimeが必要 |
| public.job_recommendation_flags | member_id, job_id | UUID（Uuid） |
| public.job_recommendation_flags | center_code | Text |
| public.job_recommendation_flags | is_recommended | Boolean |

`id`は安定した一意ID、推薦は会員・求人への整合した参照であることが期待される。
Clause自体にPK / FK / UNIQUE / NOT NULLのDDL定義はない。
`job_code`は宣言・全求人列SELECTには含まれるが、ID検索・domain projectionには使用しない。
求人titleはdomain上の必須文字列。summary / location / schedule等は後述のnullable projectionに従う。
NULL statusや未定義statusは現在のenum変換でUNKNOWNとなる。DBで許容する値・NULLの実態は未確認。

### Identifiers and scope

- `external_member_id = str(members.id)`。通常のUUID文字列表現で返す。
- `member_number = members.member_code`。会員番号をIDにfallbackしない。
- `external_job_id = str(jobs.id)`。`job_code`は業務コードでありIDの代用にしない。
- `service_id`、`organization_id`、`center_code`は別の責務。
  `ADMIN_INTERNAL_API_SCOPES`でservice → organization、
  `CURRENT_DB_BUSINESS_CENTERS`でorganization → centerを解決する。
- 空・不正なcenter mappingは`ExternalBusinessNotConfiguredError`。
  未登録organizationは`OrganizationServiceScopeNotConfiguredError`で、DB照会前に失敗する。
  organizationをcenterとして使うfallbackはない。
- Internal APIはtrusted service mappingを使い、browserから任意のcenterを指定するcontractはない。
  Staff経路のservice認可、runner execution ownershipもcenter mappingとは別。
- UUID lookupはUUIDとしてparseする。通知validationの結果照合とInternal Serviceの応答ID整合確認は
  文字列等値を使うため、Gatewayが返したcanonical ID文字列をそのまま引き回す。

### Member verification / summary

本人照合はcenter内で`member_code == member_number`かつ`full_name == name`。
コードによるtrim・normalization・fuzzy / partial matchingはない。SQL等値の実際の
collation挙動はManual Gateで確認する。最大2件を取得し、0件はNO_MATCH、
1件はUNIQUE_MATCHとUUID ID、2件以上はMULTIPLE_MATCH。
Unique以外はdomain IDがNone、Internal APIではIDキー自体を返さない。

SummaryはcenterとUUID `members.id`で検索し、
`external_member_id`と`display_label = full_name`だけを返す。
不存在・他center・UUIDとして不正なIDはExternalMemberNotFoundError。
生年月日・住所・電話・LINE subject等は追加しない。

### Recommended jobs / candidates

推薦はmembers → job_recommendation_flags → jobsのjoin。
member_id / job_idを結合し、**3 tableそれぞれ**のcenterが解決済みcenterと一致、
is_recommendedがtrueの場合だけ返す。Flagだけscope一致でも他centerの会員・求人を通さない。
先に会員summaryを確認し、不存在と「推薦0件」を区別する。

推薦順はjobs.id ASC。Ranking / scoreはない。Adapterはpublished限定にしない
（LINEの公開求人表示側の認可・filterとは別）。
候補者検索も同じ3 tableのscopeとtrue flagを使い、members.id ASC。
CandidateはID、full_name、eligible=true、空reason_codesを返し、
match_rank / line_subject / preference_summaryはNone。
候補者検索自体ではjob status / revisionを検証しない。最終適格性は通知validationで判定する。

### Job mapping

| Domain field | Current DB source / behavior |
| --- | --- |
| external_job_id | str(jobs.id) |
| title | title |
| Summary.summary | summaryをそのまま |
| Detail.description | summary or 空文字（NULL・空文字とも空文字） |
| Summary.work_location_summary / Detail.work_location | location_text |
| Summary.work_schedule_summary / Detail.work_schedule_text | work_date_text |
| status | JobStatus: draft / published / paused / closed / cancelled / unknown。未定義値はUNKNOWN |
| version / updated_at | updated_atをUTCへ変換しISO文字列 / datetimeとして返す |
| application_deadline | None |
| Detail.required_conditions | 空tuple |
| Detail.staff_notes / job_url | None |
| Summary.work_days / work_time | None |

DetailはcenterとUUIDで検索。不存在・他center・不正UUIDはExternalJobNotFoundError。
取得元のない情報を推測しない。`published_at`は参照clauseにもなく、
revision・締切への転用もない。

### Search / count / pagination

`search_jobs`は以下をcountとitemsの両方へ適用する。

- 解決したcenterの等値条件。
- statusesが非空ならstatus IN（enumの文字列値）。空tuple / Noneならstatus条件なし。
- updated_from以上・updated_to以下（両端inclusive）。
- keywordが空白以外ならtrimし、title / summary / location_textに
  `ILIKE %keyword%`のOR。SQL wildcardの% / _はescapeしない現行仕様。
- Orderはupdated_at DESC、id ASC。Pageは1始まり、offset=(page−1)×page_size、limit=page_size。
  JobSearchQueryはpage / page_size >= 1を要求し、defaultは1 / 20。
- Countは`func.count().label("total")`を使い、
  `count_rows[0]["total"]`でRowMapping参照する。整数index参照には戻さない。
- Domain field名は`total_count`。0件は0・items空・has_next=false。
  `has_next = page * page_size < total_count`。範囲外pageでもtotal_countは一致する。
  Countとitemsは別SELECTであり、同時更新時のsnapshot一貫性を新たに保証するものではない。

### Revision / notification validation

`jobs.updated_at`はtimezone-aware datetime必須。UTCへ変換し、
`astimezone(timezone.utc).isoformat()`をversionとする。
None・naive datetime・不正な値はExternalSystemUnavailableError。
別日時や現在時刻で補完しない。Version比較は文字列等値で、数値・日時順序比較ではない。
更新時にupdated_atが変わる仕組みは実DBのManual Gateで確認する。

`validate_notification_targets`の現行依存は次のとおり。

- Job UUIDとcenterで存在を確認。存在しない / 他centerならjob_eligible=false、
  JOB_NOT_FOUND、current_job_versionは空文字、membersは空tuple。
  不正なjob UUIDはExternalJobNotFoundError。
- PUBLISHEDだけstatus上適格。CLOSED / PAUSED / CANCELLEDは対応reason、
  DRAFT / UNKNOWN等はUNKNOWN。Revisionが不正なら依存障害。
- 指定member UUIDとcenterを検索し、同じjob・centerのrecommendationをouter join。
  不在・他center・不正member UUIDはMEMBER_NOT_FOUND、
  flagなし / falseはMEMBER_NO_LONGER_CANDIDATE。
- 推薦trueのmemberはjob statusが適格かつexpected_job_versionが一致した場合だけeligible。
  Version相違はjob-level JOB_VERSION_CHANGED。Job理由で不適格な推薦memberの
  member reasonはNoneの場合があり、job-level結果と合わせて判断する。
- Active属性、独自スコア、追加資格やLINE連携状態をbusiness schemaから推測しない。
  validated_atは検証時刻であり、job versionの取得元ではない。

[NotificationService](../backend/app/application/notification_service.py)は送信時にも
validate_operationを再実行し、get_job_detail / list_candidate_members /
validate_notification_targetsを呼ぶ。その後、Phase 1のsend capability guardが
永続outbox予約前に送信可否と人数を再確認する。
Business validationとLINE sender最終制限は別の責務で、今回どちらも変更しない。
`check_link_eligibility`だけは引き続き未設定例外を返す。本人照合を連携可否の代用にしない。

### Errors / read-only ownership

| 状況 | Adapter / Internal API |
| --- | --- |
| 会員・求人lookup不存在 / 不正UUID | 対応NotFound例外 / 404 resource_not_found |
| Organization未設定 | Scope例外 / 403 scope_forbidden |
| Center mapping空・不正 | ExternalBusinessNotConfiguredError / 503 external_system_unavailable |
| SQLAlchemyError / TimeoutError / OSError | 固定文言のExternalSystemUnavailableError / 503 external_system_unavailable |
| NULL / naive / 不正timestamp | ExternalSystemUnavailableError / 503 external_system_unavailable |
| 未定義status | JobStatus.UNKNOWN（DB障害へ変換しない） |
| 想定外例外 | InternalRouteが500 internal_errorへ変換 |

通知validationのjob不在は前節の業務結果であり、lookupの404とは区別する。
SQL本文・bind値・接続情報・raw exceptionをInternal HTTP responseへ出さない。
Proxy / APMログの確認はManual Gate。エラー体系の再設計はしない。

AdapterはSELECTのみ。INSERT / UPDATE / DELETE / DDL / reflection / create_all /
migrationを持たず、business schema ownerにならない。
Admin-owned通知5 tables・Staff tables、LINE-owned canonical 3 tablesとは別owner。
同じDATABASE_URLを使う現在compositionでも、この責務分離は変わらない。
Businessへのpersistence用FK追加や、LINE legacy metadata全体のcreate_allは行わない。
LINE旧business metadataはこのexpected schemaの正本ではない。

現在のInternal API既定providerと明示runner ownership付きAdmin canonical compositionは
Current DB Adapterを使用する。必要設定なしにFakeへfallbackしない。
Engineは注入可能であり、将来Production providerへ差し替えるためにdomain / Internal APIを変更しない。

### DEPLOYMENT-PRECHECK MANUAL GATE — 実DBでは未実施

[Deployment Runbook](DEPLOYMENT_RUNBOOK.md)のDB gateに、以下をschema照合の詳細として適用する。
本SliceではDB接続・introspection・SQL発行・migration・actual env読取りを行わない。

- [ ] public.membersの存在、上表全列、UUID id、member_code / full_name / center_codeの型とNULL・照合規則。
- [ ] public.jobsの存在、上表全列、UUID id、status実値、center_code、updated_atが非NULLかつtimezone-aware。
- [ ] public.job_recommendation_flagsの存在、上表全列、UUID member_id / job_id、boolean is_recommended、center_code。
- [ ] IDsの一意性・安定性、recommendation→member / jobの参照、3 tableのcenter整合、重複flagの有無。
  PK / FK / UNIQUEの実定義を記録する。コードは推薦の重複をdistinct化しないため重複を放置しない。
- [ ] 同centerの本人照合unique / no match / multiple matchの取扱い、空白や会員番号先頭ゼロの保持。
  実constraintでmultiple matchが不可能な場合は、その定義とoffline coverageを記録し実データを壊して再現しない。
- [ ] Summary、推薦（0件・他center除外）、job detail、求人検索のstatus / keyword / 日時 / pagination / countを確認。
- [ ] Job更新でversionが変わること、UTC変換、送信前のstatus / 推薦取消 / version変更が拒否されること。
- [ ] Admin runtime userがbusiness 3 tablesをSELECT可能。Adapterにbusiness write権限は不要。
  同じユーザーのowned persistence書込み権限とは分けて確認する。
- [ ] 未対応項目のNone / 空値とsummary→descriptionの表示が検証用途に適すること。
- [ ] 相違があればbaseline判定を保留し、観測結果を別途記録する。コードへ合わせるmigrationを本Sliceで行わない。

### Focused offline verification

[test_current_db_external_business.py](../backend/tests/test_current_db_external_business.py)は
test-only SQLiteとasync connection doubleでSELECT / join / scope / mappingを確認する。
SQLiteのtimezone制約はdoubleで補い、revision変換は別の直接テストで確認する。
これは実PostgreSQLの型・collation・権限・制約・更新triggerを確認した証拠ではない。

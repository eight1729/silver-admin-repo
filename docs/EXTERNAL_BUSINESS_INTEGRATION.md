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

## Current DB Adapter — Slice 1.3

人間による検証 DB の schema 確認結果を根拠として、
`backend/app/adapter/current_db_external_business.py` に read-only Adapter を実装する。
ここでの UUID / table / revision の取り決めは Current DB に限定され、将来の
Production Adapter の ID や schema を規定しない。Domain / Internal API は変更しない。

| Domain | Current DB mapping |
| --- | --- |
| 本人照合の会員番号・氏名 | `public.members.member_code` と `full_name` の等値検索。加工しない。 |
| `external_member_id` | `public.members.id`（UUID PRIMARY KEY）。人間が Current DB の安定 ID と確認済み。 |
| Summary `display_label` | `members.full_name`。ID とラベルの2項目だけ取得する。 |
| `external_job_id` | `public.jobs.id`（UUID PRIMARY KEY）。`job_code` は別の業務コードで、ID検索には使わない。 |
| 推薦元 | `public.job_recommendation_flags`。`member_id` / `job_id` で会員・求人へ結合し、`is_recommended = true`。 |
| scope | 信頼する organization → `center_code` の設定。会員・推薦フラグ・求人の全対象に等値条件を適用。 |
| `version` / `updated_at` | `jobs.updated_at` を UTC に変換。version は `astimezone(timezone.utc).isoformat()`。 |

人間確認済み制約は `(center_code, member_code)` と `(center_code, job_code)` の
UNIQUE、推薦の `(center_code, job_id, member_id)` UNIQUE、推薦から会員・求人への FK。
確認時点で推薦の参照欠落・center 不整合はない。Adapter はこの観測だけに依存せず、
全 join 対象の center を検証する。照合は最大2件を取得し、UNIQUE 制約下では通常
発生しない複数件も既存の `MULTIPLE_MATCH` として表す。

求人のタイトル・概要は `title` / `summary`、所在地は `location_text`、日程は
`work_date_text` を使う。独立した詳細説明の取得元は提示されていないため、
Current DB の `description` は `summary` を利用し、NULL のときは空文字とする。
対応元がない締切・職員メモ・URL・追加勤務項目は `None`、必要条件は空 tuple。
`published_at` は公開日時として確認済みだが、既存 domain に該当欄がないため
取得・露出せず、更新日時や締切へ転用しない。
status は既存 `JobStatus` と一致する値を使い、未定義値は `UNKNOWN`。
既存推薦 contract は公開求人限定を要求しないため、新たな status フィルタは追加しない。
推薦の順序は ID 順で固定し、score・ranking の意味は持たせない。

`updated_at` には人間確認済みの BEFORE UPDATE trigger がある。この更新日時を
Current DB の revision とする。NULL・timezone のない日時からは revision を捏造せず、
依存障害とする。不存在または scope 外の会員・求人は既存 not-found 例外、DB 障害は
`ExternalSystemUnavailableError` に変換し、SQL・引数・接続情報を応答に含めない。

### Configuration and runtime

追加設定は `CURRENT_DB_BUSINESS_CENTERS` のみ。organization ID → Current DB の
center_code を JSON object で運用設定する。既存 `ADMIN_INTERNAL_API_SCOPES` の
service → organization 解決を維持し、その後 Adapter が center を解決する。
設定は `.env.example` に空の placeholder のみ追加。実 `.env` は変更しない。
空・不正な設定は依存未設定、未登録 organization は scope エラーとして fail closed。
organization ID と center_code の同一性を仮定した fallback は行わない。

Internal API の既定 Provider は Current DB Adapter。既存 `get_engine()` / AsyncConnection
を使い、現在の `DATABASE_URL` を再利用するが、Adapter は engine 注入を受けるため
通知 persistence と同一 DB であることを Application / domain の前提にしない。
既存ローカルスタッフ画面の composition は変更せず、Internal API の Fake fallback
だけを外す。将来の Provider は既存の明示 Gateway 注入で差し替えられる。

対象4機能以外の Port メソッド（連携可否・全求人検索・候補者検索・通知対象検証）は、
確認済み業務ルールがないため未設定例外を返す。今回の Adapter をそれらの実装済み
Provider としてスタッフ通知経路へ接続しない。

### Verification and manual gate

focused tests はテスト内の relational DB / async connection double で SELECT・join・
scope 分離を実行する。SQLite はテスト限定で、timestamp は PostgreSQL 相当の
timezone-aware 値を double が返す。実 DB・実データ・実 `.env` へのアクセスはしない。
SQLAlchemy の table clause は参照専用で、共有 metadata・DDL・migration は追加しない。

運用時には以下を手動確認する:

- 許可 service / organization と center の設定、および3テーブルへの読取権限。
- 実接続で4 endpoint が動作し、別 center の情報を返さないこと。
- `updated_at` が timezone-aware かつ非 NULL で、更新時に revision が変わること。
- Current DB の概要を詳細説明にも使う表示と、未対応任意項目の空値が検証用途に適すること。

LINE identity table・登録詳細を参照せず、DB schema / データ変更と Phase 2 は行わない。

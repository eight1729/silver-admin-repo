# Silver Admin Repository

## 概要

このリポジトリは、シルバー人材センター向けシステムのうち、**スタッフ管理画面および通知管理を担当する Admin 側システム**です。

LINE / LIFF 側の実装とはリポジトリを分離しており、Admin 側から LINE 側へは **HTTP API とバージョン管理された OpenAPI 契約**を介して連携します。LINE 側の実装コードを直接参照する構成にはしていません。

## 役割

Admin Repository が主に担当する範囲は次のとおりです。

- スタッフ向け管理画面
- 求人・候補者情報の参照
- 通知対象の選択
- 通知内容の作成・確認
- 通知処理の受付
- 通知処理・配送状態の保存
- Outbox を用いた LINE 側への送信依頼
- スタッフ認証・権限管理
- External Business System との接続境界
- LINE Internal API の HTTP Consumer

LINE Messaging API、LIFF、LINE ユーザーとの紐付け、実際の LINE 配信処理は LINE Repository 側の責任です。

## 全体構成

```text
Admin Frontend
      |
      v
Admin Backend
      |
      +--------------------+
      |                    |
      v                    v
External Business      Admin Database
Gateway                / Outbox
      |                    |
      |                    v
      |              LINE HTTP Consumer
      |                    |
      +--------------------+
                           |
                           | HTTP
                           | line-internal-api-v1
                           v
                    LINE Repository
                           |
                           v
                    LINE Messaging API
```

Admin と LINE の境界は、原則として次の2点です。

1. HTTP 通信
2. `line-internal-api-v1.openapi.json` による契約

相手リポジトリのソースコードやファイルシステムを直接参照することは想定していません。

## External Business System との関係

会員、求人、推薦・マッチング等の業務情報については、外部業務システム側を正本とする設計です。

Admin Repository では External Business System との接続を `ExternalBusinessGateway` 境界として分離しています。標準 runtime は設定済みの Current DB Adapter を使用し、runtime Fake や fixture を自動選択しません。Current DB Adapter は release 前の検証用実装であり、外部業務システムの本番仕様を表すものではありません。

実際の外部業務システムとの接続方法は、API、DB 接続その他の方式を含め、接続先の仕様に応じてこの境界の内側で実装する想定です。

## 通知処理の基本的な流れ

```text
1. Admin Frontend から通知操作を開始
        |
2. Admin Backend が対象・内容を検証
        |
3. Admin DB に通知操作を保存
        |
4. Outbox に LINE 側への送信依頼を保存
        |
5. LINE HTTP Consumer が LINE Internal API を呼び出す
        |
6. LINE Repository が LINE 配信処理を実行
        |
7. Admin 側が処理結果を取得・反映
```

Admin 側で LINE Messaging API を直接呼び出す構成ではありません。

## Admin 側が所有する主なデータ

Admin Repository は、主に次のテーブルを所有します。

### Notification

- `admin_notification_operations`
- `admin_notification_targets`
- `admin_notification_deliveries`
- `admin_notification_audit_events`
- `admin_notification_outbox`

### Staff

- `staff_identities`
- `staff_service_permissions`

LINE 側が所有するテーブルとは責任範囲を分離しています。

## 主なディレクトリ

```text
backend/
  app/
    main_admin.py
    api/                 Admin API / 認証
    application/         Admin application service
    runtime/             Admin runtime / dispatch
    adapter/             外部接続 adapter
    db/                  Admin persistence
    contracts/           LINE Internal API consumer model
  contracts/             OpenAPI artifacts
  scripts/               Admin 用 provisioning / OpenAPI export

frontend/
  targets/admin/         Admin 用 Next.js target
  app/admin/             Admin UI
  config/                target environment loader

docs/                    補足文書
```

Admin Backend の canonical entrypoint は次のファイルです。

```text
backend/app/main_admin.py
```

コンテナ起動も `uvicorn app.main_admin:app` を使用します。

ローカル起動手順は [docs/LOCAL_RUN.md](docs/LOCAL_RUN.md) を参照してください。

## API 契約

Admin Repository には、Admin 自身の API 契約に加えて、LINE Repository が提供する内部 API の配布済み契約を保持します。Admin Internal API の provider owner は Admin、LINE Internal API の provider owner は LINE です。契約は共有 Python package ではなく、versioned OpenAPI artifact を手動配布します。

```text
backend/contracts/admin-api-v1.openapi.json
backend/contracts/line-internal-api-v1.openapi.json
```

Admin 側は LINE provider 実装を import せず、配布された契約に基づいて HTTP 経由で利用します。

## 環境変数

実環境用の設定はリポジトリ root の次のファイルを使用します。

```text
.env.admin
```

公開・共有用の例は次のファイルです。

```text
.env.example
```

`.env.admin` には秘密情報や接続情報が含まれる可能性があるため、Git へ登録しないでください。

## 権利・利用条件

本リポジトリのコードに関する権利、改変、第三者への共有については、次の文書を参照してください。

```text
RIGHTS.md
```

正式な契約書が別途締結されている場合は、その契約内容が優先されます。
Notification runner ownership is configured separately with `ADMIN_NOTIFICATION_RUNNER_SERVICE_IDS`. `ADMIN_INTERNAL_API_SCOPES` remains an inbound API authorization map.

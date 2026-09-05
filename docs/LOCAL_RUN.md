# Admin ローカル起動手順

## 1. 前提

ローカル起動には次のものが必要です。

- Python 3 と `pip`
- Node.js と `npm`
- 接続可能な PostgreSQL Database
- Repository root に配置した `.env.admin`

## 2. 初回セットアップ

Repository root で、Backend の Python dependency を導入します。

```powershell
cd C:\path\to\silver-admin-repo
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
```

Frontend の dependency は、`package-lock.json` に従って導入します。

```powershell
cd C:\path\to\silver-admin-repo\frontend
npm ci
```

## 3. 環境変数

Repository root の [`.env.example`](../.env.example) を参照し、同じ場所に `.env.admin` を用意してください。少なくとも、Backend が使用する Database 接続設定と、Frontend から Admin Backend へ接続するための次の公開設定が必要です。

```dotenv
NEXT_PUBLIC_ADMIN_API_BASE_URL=http://127.0.0.1:8082
NEXT_PUBLIC_ADMIN_SERVICE_ID=<使用するサービスID>
```

Backend が Frontend origin を許可するよう、`ADMIN_CORS_ALLOWED_ORIGINS` に `http://127.0.0.1:3001` を設定してください。その他の値は利用環境に応じて `.env.example` を基準に設定します。秘密情報や接続情報は文書やGit管理対象へ記載しないでください。

Backend と Admin Frontend は、どちらもsource/configの位置からRepository rootの `.env.admin` を参照します。Frontend loaderが読み込むのは `APP_ENV` と `NEXT_PUBLIC_*` のみです。また、起動済みPowerShellに同名の環境変数がある場合は、その値が `.env.admin` より優先されます。

## 4. Admin Backendの起動

WindowsでPostgreSQLを利用する場合は、既知の動作確認済み手順としてSelector event loopを明示します。Repository rootで次を実行してください。

```powershell
cd C:\path\to\silver-admin-repo
$env:PYTHONPATH="backend"

@'
import asyncio
import selectors
import uvicorn
from app.main_admin import app

config = uvicorn.Config(
    app,
    host="127.0.0.1",
    port=8082,
    loop="asyncio",
)
server = uvicorn.Server(config)

asyncio.run(
    server.serve(),
    loop_factory=lambda: asyncio.SelectorEventLoop(
        selectors.SelectSelector()
    ),
)
'@ | python
```

canonical entrypointは `backend/app/main_admin.py` です。Repository rootから `app` packageをimportするため、上記手順では `PYTHONPATH=backend` を設定しています。

## 5. Backend確認

別のPowerShellでhealth endpointを確認します。

```powershell
curl.exe http://127.0.0.1:8082/health
```

HTTP 200と、Admin Backendを示すJSONが返れば起動できています。このendpointはDatabase接続確認ではなく、application processのhealth確認です。

## 6. Admin Frontendの起動

Backendとは別のPowerShellを開き、Frontend directoryからAdmin targetを起動します。

```powershell
cd C:\path\to\silver-admin-repo\frontend
npm run dev -- -p 3001
```

このcommandは `frontend/package.json` の `dev` scriptを使用し、`targets/admin` をNext.js applicationとして起動します。

## 7. Admin画面確認

ブラウザで次を開きます。

```text
http://127.0.0.1:3001/admin
```

最低限、次を確認してください。

- Admin画面が表示される
- 求人情報が読み込まれる
- ブラウザからAdmin Backendへのrequestが成功する

求人情報の取得には、`.env.admin` のDatabase・local integration・認証関連設定が実行環境に合っている必要があります。

## 8. 停止方法

BackendとFrontendは、それぞれを起動したPowerShellで `Ctrl + C` を押して停止します。

## 9. よくある注意点

- `.env.admin` がRepository rootにない場合、Backendの必須設定を解決できません。
- Frontendのcommandは `frontend` directoryで実行してください。
- 古いPowerShell sessionに残る `NEXT_PUBLIC_*` は `.env.admin` の同名設定より優先されます。設定変更後は新しいsessionで起動してください。
- `8082` または `3001` が既に使用中の場合、対応するprocessを起動できません。
- WindowsでPostgreSQL接続時にevent loop由来の接続問題が起きる場合は、通常のUvicorn commandではなく「4. Admin Backendの起動」のSelector event loop手順を使用してください。

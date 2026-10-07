# Admin local / production 起動手順

正式なAPP_ENVは `local` / `production` のみです。旧staging/development/demo/test、未知値・未設定は拒否します。NODE_ENVはNext.jsの別概念です。

## localの構成

localは実サービスによる統合検証環境です。両環境でGoogle GIS popup/callback、Backend OIDC署名・issuer・audience・expiry・sub検証、Staff DB identity/active/service permission/roleを使用します。Demo認証へfallbackしません。

~~~text
Admin Frontend (3001) -> Admin Backend (8082)
                         |-> 開発PostgreSQL (Current DB / Staff / notification persistence)
                         |-> https://silver-backend.ngrok.app -> Local LINE Backend -> LINE Messaging API
~~~

Python 3.12、Node.js 22（testsは22.13以降）、npmを使用します。依存の正本はbackend/requirements.txtとfrontend/package-lock.jsonです。依存導入、実env設定、実起動・実操作は人間が行います。

## 人間によるlocal設定

1. .env.admin.exampleを参考にrepository rootの実.env.adminを人間が設定します。local専用です。.env.exampleも同内容の参考templateです。
2. Backend/Frontendを起動する両PowerShellで `$env:APP_ENV="local"` を明示します。dotenv内のAPP_ENVは環境選択に使われません。
3. process envはowner dotenvより優先され、空文字も優先されます。古いshellの設定を確認してください。実secretはログやチャットへ貼らないでください。
4. DATABASE_URLは開発DB。ADMIN_EXTERNAL_BUSINESS_BASE_URLを未設定/空にするとCurrent DB adapterを使います。外部業務APIは必須ではなく、Fakeにもfallbackしません。
5. ADMIN_INTERNAL_API_SCOPESはservice_id -> organization_id、CURRENT_DB_BUSINESS_CENTERSはorganization_id -> center_codeのJSONです。ADMIN_NOTIFICATION_RUNNER_SERVICE_IDSは所有serviceの明示リスト。旧ADMIN_LOCAL_INTEGRATION_MODE / ADMIN_LOCAL_INTEGRATION_SCOPESは廃止しました。
6. ADMIN_OIDC_ENABLED=true、issuer、audience、JWKS URL、許可algorithmを設定します。公開NEXT_PUBLIC_GOOGLE_CLIENT_IDとADMIN_OIDC_AUDIENCEは同じGoogle Web Client ID。StaffはDBのissuer + subjectとservice permissionで照合し、emailだけでは認可しません。
7. NEXT_PUBLIC_ADMIN_API_BASE_URL=http://127.0.0.1:8082。空文字はエラーでありsame-originではありません。NEXT_PUBLIC_API_BASE_URL fallbackはownerキーが完全に未定義のときだけ有効です。
8. NEXT_PUBLIC_ADMIN_SERVICE_IDにはStaff権限のあるserviceを指定。GoogleのAuthorized JavaScript Originには実際にブラウザで開くFrontend originを人間が登録します。popup/callbackを維持し、redirect方式へ変更しません。
9. ADMIN_CORS_ALLOWED_ORIGINSに実Frontend originを登録します。http://localhost:3001とhttp://127.0.0.1:3001は別origin。両方使うならカンマ区切りで両方登録します。
10. ADMIN_LINE_INTERNAL_API_BASE_URL=https://silver-backend.ngrok.app。ADMIN_LINE_INTERNAL_API_BEARER_TOKENは同じlocal LINEのLINE_INTERNAL_API_BEARER_TOKENと対応する値です。
11. ADMIN_INTERNAL_API_BEARER_TOKENは逆方向LINE -> Admin用で、LINE_ADMIN_INTERNAL_API_BEARER_TOKENと対応。送信用Bearer・Google Staff Tokenと共用/fallbackしません。

Adminはlocalhost構成を標準とし、Admin用ngrokは必須ではありません。fixed HTTPSを使うなら公開Frontend originをGoogle/CORSへ、公開Backend URLをFrontendへ設定します。LINE -> Adminの実検証で必要なら、人間がAdmin Backendの外部到達性を確保します。

## Windows Backend: canonical SelectorEventLoop

Python 3.12を使用します。Windows既定event loopによるasync psycopg接続問題を避けるため、次の既存方式を使用します。

~~~powershell
cd C:\path\to\silver-admin-repo
$env:APP_ENV="local"
$env:PYTHONPATH="backend"
@'
import asyncio
import selectors
import uvicorn
from app.main_admin import app

config = uvicorn.Config(app, host="127.0.0.1", port=8082, loop="asyncio")
server = uvicorn.Server(config)
asyncio.run(
    server.serve(),
    loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
)
'@ | python
~~~

canonical entrypointはbackend/app/main_admin.pyです。必要設定不足時は起動失敗します。/healthはprocess healthのみで、DB/OIDC/LINEの成功確認ではありません。

## Frontend

別PowerShellで実行します。

~~~powershell
cd C:\path\to\silver-admin-repo\frontend
$env:APP_ENV="local"
npm run dev -- -p 3001
~~~

canonical targetはfrontend/targets/adminです。npm run dev/build/startはenv検証launcherを経由します。nextを直接呼ばないでください。Next target内の標準.env / .env.local / .env.production*等は禁止し、Nextが読む前にファイル名検査で拒否します。localのowner .env.adminだけを許可します。

ブラウザでGoogleに登録したoriginの/adminを開き、Google Loginを人間が確認します。

## 送信制御とManual Gate

Backendはlocalでselected target count > 10を送信予約・Delivery/Outbox生成前に拒否します。11 selected / 10 sendable（1 skipped）も拒否します。10以下でもLINE capabilityがready=false、取得失敗、上限超過なら拒否します。productionには固定10人上限を適用しません。

Frontendにもlocal有効上限（10とLINE上限の小さい方）を返します。UIだけを安全根拠にはしません。staging_liveはlocal安全送信を表す既存wire labelで、APP_ENV=stagingではありません。旧readiness endpoint/schemaも維持します。

runnerは起動後に保存済み未完了Operationを再開します。接続前に開発DB・所有service・未完了送信を人間が確認してください。DB schema/migration/provisioning変更はこのSliceに含みません。

人間が確認する項目：Google Origin、開発Staff identity/permission、開発DB、LINE local安全設定、ngrok、両BackendとFrontend起動、Google Login、1人送信、複数人送信、10人境界、11人拒否、sender icon表示。

## production

APP_ENV=productionと全設定をCloud process env / Secretで指定します。Backend/Frontendともlocal owner dotenvへfallbackしません。不足設定はstartup/buildを失敗させます。production DB、LINE Backend、双方向Bearerをlocalと分離し、LINE/外部業務APIへのHTTPSを維持します。HTTPSだけでは接続先環境を識別できないため、URLとcredentialの組合せを人間が確認します。

NEXT_PUBLIC_*はbuild-timeにbundleへ固定され、runtime env変更だけでは接続先を切り替えられません。変更時は再buildし、APP_ENVと公開設定をbuild/startで一致させます。VercelでもBuild Commandはnpm run buildを使用し、Cloud側で設定します。deploymentは人間が実施します。

## Offline検証

Backend: backend directoryでpython -m pytest。test harnessが実dotenv・外部socket・PostgreSQL接続を拒否します。SQL回帰testsは破棄可能なin-memory SQLiteのみ。PostgreSQLロック等の実動作はManual Gateです。
Frontend: npm test、npm run test:config、npm run typecheck。production build検証にはAPP_ENV=productionとdummy公開設定を明示し、実envを使いません。

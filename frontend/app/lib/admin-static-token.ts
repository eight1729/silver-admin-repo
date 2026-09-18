// staging 用の入口の鍵を Admin API の呼び出しに載せる。
//
// backend 側は `/health` 以外の全経路に共有 Bearer を要求する
// （`backend/app/api/static_bearer.py`）。APP_ENV=staging は全リクエストを認証なしの
// Admin ロールとして扱うため、鍵が無いと URL を知る誰でも台帳を操作できてしまう。
//
// これは「認証」ではなく入口の鍵で、**誰が操作したかは記録されない**。
// 職員の識別は production の OIDC で行う。
//
// ★`NEXT_PUBLIC_ADMIN_STATIC_TOKEN` が設定されているときだけ登録する。
//   無条件に登録すると、production の ID トークンを返す provider を上書きしてしまう。

import { registerAdminAccessTokenProvider } from "./admin-api";

const staticToken = process.env.NEXT_PUBLIC_ADMIN_STATIC_TOKEN;

if (staticToken) {
  registerAdminAccessTokenProvider(() => staticToken);
}

export const adminStaticTokenConfigured = Boolean(staticToken);

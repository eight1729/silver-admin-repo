# Current DB 推薦レベル・テストfixture v1（手動適用専用）

このnamespaceは既存のbusiness migration/seedが両repoに存在しないため新設した手動成果物です。Admin通知/staff provisionerやLINE migrationへ接続しません。適用済みmigrationの改変、アプリ起動時の自動実行、DB接続コードはありません。

## 意味と対象

- `is_recommended BOOLEAN NOT NULL DEFAULT true`は従来の手動候補可否。変更しません。
- `recommendation_level INTEGER NULL CHECK (1 <= level AND level <= 5)`は別の推薦強度。defaultなし。NULLは未評価です。既存trueを5へ変換せず、既存65件はNULLのまま保ちます。
- fixtureのlevel 1〜5は全てbool=true。1〜4も手動候補として残ります。bool=falseならlevel5でも候補になりません。
- 将来の自動選択条件はlevel=5 AND 別途取得するline_linked=true、会員番号の**数値降順**、最大100人。現在のboolへの置換ではありません。今回は自動選択ロジック/UI/LINE状態を実装しません。

ユーザー確認済み対象は`center_code=sumida`の会員コード数値1〜30（30人）、`TEST-JOB-001`〜`010`（10求人・published）、既存true推薦65件です。件数だけで別環境のデータを認定しないでください。この確認を根拠にしたfixtureで、汎用seedではありません。

| 対象 | 初回 | 追加 | 適用・再適用後 |
|---|---:|---:|---:|
| 会員 | 30 | 90 | 120 |
| 求人 | 10 | 3 | 13 |
| 推薦 | 65（未評価） | 360（評価済み） | 425 |

新会員31〜70が一般40人、71〜120が最新50人です。元コードのゼロ埋めは保持し、新コードは十進文字列31〜120です。元30人のcreated_at最大値を固定基準に、追加会員へ1〜90時間を順に加算します。再実行でも同じ日時で、最新50人は全旧会員・一般40人より後です。

専用求人は`REC-V1-JOB-001`〜`003`。created_at/updated_atは同基準+7/+14/+21日で分散します。既存10求人には触れません。3表のBEFORE UPDATE `set_updated_at()`を無効化せず、seedにUPDATE/DELETEはありません。既存求人のupdated_at/version、published_at、既存通知snapshotへの書込みもありません。将来日になる可能性のあるfixture日時を実際の求人公開日と扱わないでください。

各専用求人に120人分の推薦をINSERTします。001は71〜120の50人のみlevel5、それ以外は1〜4。002/003は1〜5を循環させ、旧会員・新会員を混在させます。同一会員の評価は求人によって異なります。

追加会員の`phone_mobile_normalized`は**NULL**です。実在しない保証のない電話番号を生成しません。ダミー電話番号や電話下4桁による検証は今回未充足です。下4桁列は追加しません。電話照合が必要な次工程では、正式に予約されたテスト用番号の指定を受けて別fixtureを設計してください。

## 所有権と停止条件

`generate_seed.py`が固定namespace UUIDv5から会員/求人IDを生成し、SQL内のmanifestへ記録します。コード・UUID・fixture名・管理対象payload・日時が一致する既存行だけを再利用します。同じコードの別UUID、同じUUIDの別scope/コード、変更済みpayload、想定外の推薦は例外で全transactionをrollbackします。衝突をUPDATEやON CONFLICTで補正しません。fixtureの削除機能もありません。

追加の必須列、未知の制約、権限不足などはINSERTを失敗させます。制約やtriggerを変更して通さないでください。全tableの書込み競合をlockで防ぎ、既存30/10/65行の全列JSON snapshotがseedの前後で一致することもtransaction内で確認します。長時間lockを避けるため、テスト環境で利用が止まった時間に実行してください。

## 手動適用順序（本作業では未実行）

1. **Supabaseのproject名/referenceをUIで独立に確認し、承認されたテストproject・sumida対象であることを確認**。`current_database()`は別projectでも`postgres`になり得るためDB名guardは環境認証ではありません。接続情報/秘密鍵の共有は不要です。
2. `00_preflight.sql`を読み取り実行。初回は会員30/数値max30、求人10/published10、推薦65/true65。型・PK/FK/UNIQUE・default・NULL許容・全triggerを提供済みDDLと照合。相違時は停止。対象を件数・氏名から推測して入れ替えないでください。
3. SQL Editorの同じ実行バッチの先頭へ以下2文を置き、その下へ`01_recommendation_level.sql`全体を貼り付けて実行します。database名はpreflight結果を手入力します。SQLファイルだけではguard不足で停止します。

   ```sql
   SET silver.fixture_consent = 'sumida-test-only-v1';
   SET silver.fixture_database = '<preflightで確認したDB名>';
   ```

4. `03_verify.sql`で**migration後・seed前**のlegacy fingerprintを控えます。後半の最終件数期待値はこの時点では未達で正常です。schema追加前のflag fingerprintとは比較しません。
5. 同じ2 guard文の下へ`02_seed.sql`全体を貼り付けて実行。ファイルのBEGIN/COMMIT・DOを分割実行しません。失敗時はROLLBACKし原因を確認。既存行を削除/修正して帳尻を合わせません。
6. `03_verify.sql`を実行。legacy fingerprint一致、120/13/425、未評価65/評価360、latest=true、001のlevel5が50人かつcode71〜120を確認。
7. 同じ`02_seed.sql`を再実行して再度03を確認。件数・legacy fingerprint・fixture内容が不変であることを**実PostgreSQLで確認するmanual gate**です。
8. **migrationを先に適用してから**Current DB Adapter変更を配置。新adapterはlevel列をSELECTするため旧schemaには配置できません。seedはテスト用のみ。運用環境への自動適用は禁止です。

`01`は再実行時に型・nullable・defaultなし・名前付きCHECKの一致を確認します。不一致は修正せず停止します。既存boolのNOT NULL/default trueも確認します。`03`はSELECTのみで個人情報値を出さず、集計・hashを返します。

## オフライン検証と限界

```powershell
python backend/manual_sql/current_db_recommendation_v1/generate_seed.py --check
python -m pytest backend/tests/test_current_db_fixture_sql.py backend/tests/test_current_db_external_business.py backend/tests/test_candidate_member_number.py -q
```

manifest生成は標準ライブラリのみで、設定/アプリ/ネットワークを読みません。SQLiteでは生成SQLのVALUES、INSERT SELECT、所有権照合predicate（ROW構文のみ変換）を実行し、30/10/65→120/13/425、同一再実行、衝突時非上書き、日時分散、最新50、レベルと既存boolを検証します。adapterの既存offline suiteは実dotenv・外部通信・PostgreSQL接続を禁止します。

**PostgreSQLのDO block、catalog検査、transaction/lock、FK、実trigger、Supabase権限、実SQL全体の再実行はオフラインでは未検証**です。SQLite成功をSupabase適用成功と扱いません。DDLの最終照合と上記手動実行が必要です。

Current DB Adapter→CandidateMember内だけlevelを投影します。Admin API/internal API/HTTP provider/外部事業者契約に新fieldを要求せず、画面表示も増やしません。LINE repo・連携情報・認証・送信上限・outbox・監査処理の変更はありません。

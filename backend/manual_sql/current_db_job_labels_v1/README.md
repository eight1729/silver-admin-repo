# Current DB 専用3求人のテスト表示名更新

実DB適用は人間が確認して行う。旧10求人、members（0031〜0120を含む）、推薦、Operationには書き込まない。

## 手順

1. 対象がテストSupabase projectであることをUIで確認。`SELECT current_database();`を実行する。DB名だけではprojectを識別できない。
2. 下記確認SQLの結果を保存する。通知作成・送信を停止し、進行中送信がないことを確認する。
3. `01_update.sql`の実行用コピーでconsentを`sumida-job-labels-test-only-v1`、databaseを確認したDB名へ置換し、BEGIN〜COMMITを一括実行する。セッション設定の引継ぎは不要。
4. エラー、lock timeout、未知の既存文言、件数不一致、未完了送信があれば停止。途中実行はしない。開いたtransactionが残った場合はROLLBACKする。ガードを外さない。
5. 確認SQLを再実行し、3求人の表示内容と更新日時、推薦件数が変わっていないことを確認する。

```sql
SELECT current_database();
SELECT j.id,j.job_code,j.title,j.summary,j.location_text,j.work_date_text,
       j.status,j.created_at,j.updated_at,
       (SELECT count(*) FROM public.job_recommendation_flags r WHERE r.job_id=j.id) AS recommendations
FROM public.jobs j WHERE j.center_code='sumida'
  AND j.job_code IN ('REC-V1-JOB-001','REC-V1-JOB-002','REC-V1-JOB-003') ORDER BY j.job_code;
SELECT o.status,count(*) FROM public.admin_notification_operations o
JOIN public.jobs j ON o.job_id=j.id::text
WHERE j.center_code='sumida' AND j.job_code IN ('REC-V1-JOB-001','REC-V1-JOB-002','REC-V1-JOB-003')
GROUP BY o.status;
```

## version・冪等性

既存triggerを有効のまま使うため、初回更新でupdated_atとCurrent DBの求人versionが変わる。created_at、ID、job_code、statusは変更しない。既存の検証・確認情報は再利用不可。旧versionの保存済み通知は再検証で停止し得るため、最新求人から新しい通知を作成して保存・検証する。履歴・既存Operationは削除・改変しない。

このSQLは旧fixture文言または新文言だけを受け付ける。同じ新文言の再実行はUPDATE対象外になり、versionを再更新しない。想定外の改名は上書きせず停止する。

**`current_db_recommendation_v1/02_seed.sql`を再実行しない。** 旧seedはINSERT-onlyで厳密な文言・会員番号照合を行うため、この改名および手動の4桁member_codeと不一致になり、安全停止する。旧seedを修正して追従させたり、会員番号を元に戻したりしない。新規DBの構築と既存テストDBの改名は別手順である。

本成果物はDDL migrationではない。TEMPテーブルはtransaction終了時に消える。SQLの実行・PostgreSQLでのtrigger検証はManual Gate。

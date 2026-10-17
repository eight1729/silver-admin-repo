-- Independent test-only label update. Never rerun recommendation seed for this change.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL silver.fixture_consent = 'REPLACE_WITH_SUMIDA_LABELS_TEST_CONSENT';
SET LOCAL silver.fixture_database = 'REPLACE_WITH_VERIFIED_DATABASE_NAME';
DO $guard$
BEGIN
  IF current_setting('silver.fixture_consent', true) IS DISTINCT FROM 'sumida-job-labels-test-only-v1'
     OR current_setting('silver.fixture_database', true) IS DISTINCT FROM current_database() THEN
    RAISE EXCEPTION 'Verify test project and explicit consent; no changes applied';
  END IF;
END $guard$;

-- Block concurrent notification edits/reservations while checking and changing versions.
LOCK TABLE public.admin_notification_operations IN SHARE MODE;
LOCK TABLE public.jobs IN SHARE ROW EXCLUSIVE MODE;
CREATE TEMP TABLE _job_labels(
  id uuid PRIMARY KEY, job_code text UNIQUE, old_title text,
  title text, summary text, location_text text, work_date_text text
) ON COMMIT DROP;
INSERT INTO _job_labels VALUES
('90083af4-1f97-59d8-8980-4a3747cc1500','REC-V1-JOB-001','CURRENT-DB-REC-V1 JOB 001',
 '【テスト・募集なし】区立施設の清掃・環境整備',
 '架空の検証用求人です。施設内の床清掃、備品整理、敷地内の落ち葉回収を想定します。実際の募集・応募受付はありません。',
 '架空の区立施設（墨田区内を想定・実在施設の指定なし）','テスト設定：平日週2日、午前9時〜正午'),
('079346cf-5b83-5139-bdcc-371ceaee1163','REC-V1-JOB-002','CURRENT-DB-REC-V1 JOB 002',
 '【テスト・募集なし】公共施設の受付・案内補助',
 '架空の検証用求人です。来館者の受付、館内案内、資料の補充を想定します。実際の募集・応募受付はありません。',
 '架空の公共施設（墨田区内を想定・実在施設の指定なし）','テスト設定：平日週3日、午後1時〜午後4時'),
('9631921e-ef46-55c0-b608-84c3dbb26f3b','REC-V1-JOB-003','CURRENT-DB-REC-V1 JOB 003',
 '【テスト・募集なし】チラシ封入・軽作業',
 '架空の検証用求人です。チラシの枚数確認、封入、仕分けなど座って行う軽作業を想定します。実際の募集・応募受付はありません。',
 '架空の共同作業室（墨田区内を想定・実在施設の指定なし）','テスト設定：平日週2日、午前10時〜午後3時（休憩1時間）');

DO $check$
BEGIN
  IF (SELECT count(*) FROM public.jobs j JOIN _job_labels f ON j.id=f.id
      WHERE j.center_code='sumida' AND j.job_code=f.job_code AND j.status='published') <> 3 THEN
    RAISE EXCEPTION 'Expected exact three published fixture jobs; stop';
  END IF;
  IF EXISTS (SELECT 1 FROM public.jobs j JOIN _job_labels f ON j.id=f.id
    WHERE NOT (
      ROW(j.title,j.summary,j.location_text,j.work_date_text)
        IS NOT DISTINCT FROM ROW(f.old_title,'Dedicated recommendation fixture v1'::text,'TEST ONLY'::text,'TEST ONLY'::text)
      OR ROW(j.title,j.summary,j.location_text,j.work_date_text)
        IS NOT DISTINCT FROM ROW(f.title,f.summary,f.location_text,f.work_date_text)
    )) THEN
    RAISE EXCEPTION 'Unexpected fixture text; do not overwrite';
  END IF;
  IF EXISTS (SELECT 1 FROM public.admin_notification_operations o JOIN _job_labels f ON o.job_id=f.id::text
    WHERE o.status='sending' OR (o.send_requested_at IS NOT NULL AND o.completed_at IS NULL)) THEN
    RAISE EXCEPTION 'Unfinished send reservation exists; do not change job versions';
  END IF;
END $check$;

CREATE TEMP TABLE _job_labels_before ON COMMIT DROP AS
SELECT j.id,j.created_at,j.updated_at,
  ROW(j.title,j.summary,j.location_text,j.work_date_text)
    IS DISTINCT FROM ROW(f.title,f.summary,f.location_text,f.work_date_text) AS needs_update
FROM public.jobs j JOIN _job_labels f ON j.id=f.id;

-- updated_at is deliberately left to the existing enabled UPDATE trigger.
UPDATE public.jobs j
SET title=f.title, summary=f.summary, location_text=f.location_text, work_date_text=f.work_date_text
FROM _job_labels f
WHERE j.id=f.id AND j.job_code=f.job_code AND j.center_code='sumida'
  AND ROW(j.title,j.summary,j.location_text,j.work_date_text)
      IS DISTINCT FROM ROW(f.title,f.summary,f.location_text,f.work_date_text);

DO $verify$
BEGIN
  IF EXISTS (SELECT 1 FROM public.jobs j JOIN _job_labels f ON j.id=f.id JOIN _job_labels_before b ON b.id=j.id
      WHERE ROW(j.title,j.summary,j.location_text,j.work_date_text)
        IS DISTINCT FROM ROW(f.title,f.summary,f.location_text,f.work_date_text)
        OR j.created_at IS DISTINCT FROM b.created_at
        OR (b.needs_update AND j.updated_at IS NOT DISTINCT FROM b.updated_at)) THEN
    RAISE EXCEPTION 'Labels, registration timestamp or update trigger check failed; rolled back';
  END IF;
END $verify$;
SELECT j.job_code, j.title, j.created_at, j.updated_at
FROM public.jobs j JOIN _job_labels f ON j.id=f.id ORDER BY j.job_code;
COMMIT;

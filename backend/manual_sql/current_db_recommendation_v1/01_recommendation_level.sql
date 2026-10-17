-- MANUAL ONLY. Confirm the test project, then set both guards as described in README.
BEGIN;
-- Edit these two literals in the execution copy after checking the test project.
-- Always overwrite inherited session values; unchanged placeholders MUST fail.
SET LOCAL silver.fixture_consent = 'sumida-test-only-v1';
SET LOCAL silver.fixture_database = 'postgres';
DO $guard$
BEGIN
  IF current_setting('silver.fixture_consent', true) IS DISTINCT FROM 'sumida-test-only-v1'
     OR current_setting('silver.fixture_database', true) IS DISTINCT FROM current_database() THEN
    RAISE EXCEPTION 'Explicit test-only consent and database guard required';
  END IF;
END $guard$;

LOCK TABLE public.job_recommendation_flags IN ACCESS EXCLUSIVE MODE;
DO $migration$
DECLARE bool_default text;
BEGIN
  SELECT pg_get_expr(d.adbin, d.adrelid) INTO bool_default
  FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
  WHERE a.attrelid='public.job_recommendation_flags'::regclass
    AND a.attname='is_recommended' AND a.atttypid='boolean'::regtype AND a.attnotnull;
  IF bool_default IS DISTINCT FROM 'true' THEN
    RAISE EXCEPTION 'Expected is_recommended boolean NOT NULL DEFAULT true; no correction attempted';
  END IF;
  ALTER TABLE public.job_recommendation_flags ADD COLUMN IF NOT EXISTS recommendation_level integer;
  IF NOT EXISTS (
    SELECT 1 FROM pg_attribute a
    WHERE a.attrelid='public.job_recommendation_flags'::regclass
      AND a.attname='recommendation_level' AND a.atttypid='integer'::regtype
      AND NOT a.attnotnull AND NOT a.atthasdef AND NOT a.attisdropped
  ) THEN
    RAISE EXCEPTION 'Unexpected recommendation_level definition; no correction attempted';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.job_recommendation_flags'::regclass
             AND conname='current_db_recommendation_level_1_5') THEN
    IF NOT EXISTS (
      SELECT 1 FROM pg_constraint WHERE conrelid='public.job_recommendation_flags'::regclass
        AND conname='current_db_recommendation_level_1_5' AND contype='c' AND convalidated
        AND regexp_replace(pg_get_expr(conbin, conrelid), '[[:space:]()]', '', 'g')
              = 'recommendation_level>=1ANDrecommendation_level<=5'
    ) THEN
      RAISE EXCEPTION 'Unexpected existing level constraint; no correction attempted';
    END IF;
  ELSE
    ALTER TABLE public.job_recommendation_flags
      ADD CONSTRAINT current_db_recommendation_level_1_5
      CHECK (recommendation_level >= 1 AND recommendation_level <= 5);
  END IF;
END $migration$;
-- No default or backfill: legacy true remains unrated (NULL), never level 5.
COMMIT;

-- READ ONLY. Run against the independently verified TEST Supabase project.
SELECT current_database() AS database_name, current_user AS execution_role;
SELECT table_name,column_name,data_type,is_nullable,column_default
FROM information_schema.columns WHERE table_schema='public'
 AND table_name IN ('members','jobs','job_recommendation_flags')
ORDER BY table_name,ordinal_position;
SELECT conrelid::regclass AS table_name,conname,pg_get_constraintdef(oid) AS definition
FROM pg_constraint WHERE conrelid IN ('public.members'::regclass,'public.jobs'::regclass,'public.job_recommendation_flags'::regclass)
ORDER BY conrelid::regclass::text,conname;
SELECT tgrelid::regclass AS table_name,tgname,tgenabled,pg_get_triggerdef(oid) AS definition
FROM pg_trigger WHERE NOT tgisinternal AND tgrelid IN
 ('public.members'::regclass,'public.jobs'::regclass,'public.job_recommendation_flags'::regclass);
SELECT pg_get_functiondef('public.set_updated_at()'::regprocedure);
-- Must return zero rows. Any omitted required column blocks this fixture.
SELECT a.attrelid::regclass AS table_name,a.attname AS omitted_required_column,
 format_type(a.atttypid,a.atttypmod) AS data_type
FROM pg_attribute a JOIN (VALUES
 ('public.members'::regclass, ARRAY['id','member_code','full_name','center_code','phone_mobile_normalized','created_at','updated_at','birth_date']),
 ('public.jobs'::regclass, ARRAY['id','job_code','title','summary','location_text','work_date_text','status','center_code','created_at','updated_at']),
 ('public.job_recommendation_flags'::regclass, ARRAY['member_id','job_id','center_code','is_recommended','recommendation_level','created_at','updated_at'])
) AS targets(relid, inserted_columns) ON targets.relid=a.attrelid
WHERE a.attnum>0 AND NOT a.attisdropped AND a.attnotnull AND NOT a.atthasdef
 AND a.attidentity='' AND a.attgenerated='' AND NOT (a.attname=ANY(targets.inserted_columns))
ORDER BY a.attrelid,a.attnum;
SELECT count(*) AS member_count,
 count(DISTINCT substring(member_code from '^[0-9]+$')::numeric) AS unique_numeric_codes,
 min(substring(member_code from '^[0-9]+$')::numeric) AS numeric_min,
 max(substring(member_code from '^[0-9]+$')::numeric) AS numeric_max,
 count(*) FILTER (WHERE member_code IS NULL OR member_code !~ '^[0-9]+$') AS invalid_codes
FROM public.members WHERE center_code='sumida';
SELECT count(*) AS job_count,count(*) FILTER (WHERE status='published') AS published_count,
 count(*) FILTER (WHERE job_code IN (SELECT 'TEST-JOB-'||lpad(n::text,3,'0') FROM generate_series(1,10) n)) AS legacy_job_count
FROM public.jobs WHERE center_code='sumida';
SELECT count(*) AS flag_count,count(*) FILTER (WHERE is_recommended) AS true_count
FROM public.job_recommendation_flags WHERE center_code='sumida';

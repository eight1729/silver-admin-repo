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

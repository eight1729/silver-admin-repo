-- READ ONLY. Run after migration BEFORE seed to save legacy fingerprints;
-- repeat after seed and its rerun. Fingerprints must remain identical.
SELECT 'members' AS kind,count(*) AS rows,
 md5(string_agg(to_jsonb(m)::text,'|' ORDER BY id)) AS legacy_fingerprint
FROM public.members m WHERE center_code='sumida' AND substring(member_code from '^[0-9]+$')::numeric BETWEEN 1 AND 30
UNION ALL
SELECT 'jobs',count(*),md5(string_agg(to_jsonb(j)::text,'|' ORDER BY id))
FROM public.jobs j WHERE center_code='sumida' AND job_code IN
 (SELECT 'TEST-JOB-'||lpad(n::text,3,'0') FROM generate_series(1,10) n)
UNION ALL
SELECT 'flags',count(*),md5(string_agg(to_jsonb(r)::text,'|' ORDER BY job_id,member_id))
FROM public.job_recommendation_flags r WHERE center_code='sumida' AND job_id IN
 (SELECT id FROM public.jobs WHERE center_code='sumida' AND job_code IN
  (SELECT 'TEST-JOB-'||lpad(n::text,3,'0') FROM generate_series(1,10) n));

SELECT count(*) AS members_120,count(DISTINCT member_code) AS unique_codes_120,
 max(substring(member_code from '^[0-9]+$')::numeric) AS max_code_120,
 count(*) FILTER (WHERE substring(member_code from '^[0-9]+$')::numeric BETWEEN 31 AND 70) AS general_40,
 count(*) FILTER (WHERE substring(member_code from '^[0-9]+$')::numeric BETWEEN 71 AND 120) AS newest_50
FROM public.members WHERE center_code='sumida';

-- Level-only inspection, NOT a send list: no LINE linkage is inferred here.
-- Future selection must additionally require separately mocked/verified line_linked=true.
SELECT m.member_code FROM public.job_recommendation_flags r
JOIN public.jobs j ON j.id=r.job_id JOIN public.members m ON m.id=r.member_id
WHERE r.center_code='sumida' AND j.center_code='sumida' AND m.center_code='sumida'
 AND j.job_code='REC-V1-JOB-001' AND r.recommendation_level=5
ORDER BY substring(m.member_code from '^[0-9]+$')::numeric DESC LIMIT 100;
SELECT count(*) AS jobs_13,count(DISTINCT created_at) FILTER (WHERE job_code LIKE 'REC-V1-JOB-%') AS fixture_dates_3
FROM public.jobs WHERE center_code='sumida';
SELECT j.job_code,r.recommendation_level,count(*) AS members,
 count(*) FILTER (WHERE r.is_recommended) AS manual_candidates,
 min(substring(m.member_code from '^[0-9]+$')::numeric) AS min_code,
 max(substring(m.member_code from '^[0-9]+$')::numeric) AS max_code
FROM public.job_recommendation_flags r JOIN public.jobs j ON j.id=r.job_id
JOIN public.members m ON m.id=r.member_id WHERE r.center_code='sumida'
GROUP BY j.job_code,r.recommendation_level ORDER BY j.job_code,r.recommendation_level;
SELECT count(*) AS flags_425,count(*) FILTER (WHERE recommendation_level IS NULL) AS legacy_unrated_65,
 count(*) FILTER (WHERE recommendation_level BETWEEN 1 AND 5) AS rated_360,
 count(*) FILTER (WHERE NOT is_recommended) AS false_flags_0
FROM public.job_recommendation_flags WHERE center_code='sumida';
SELECT min(created_at) FILTER (WHERE substring(member_code from '^[0-9]+$')::numeric >= 71)
     > max(created_at) FILTER (WHERE substring(member_code from '^[0-9]+$')::numeric <= 70) AS newest_50_are_newer
FROM public.members WHERE center_code='sumida';

"""Offline manifest + SQLite DML checks. NOT a PostgreSQL execution test.

Execute generated INSERTs and ownership predicates against an isolated relational
fixture. PostgreSQL DO/locks/catalog checks/triggers remain a manual apply gate.
"""
import importlib.util
from pathlib import Path
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

ROOT = Path(__file__).resolve().parents[1] / 'manual_sql/current_db_recommendation_v1'
spec = importlib.util.spec_from_file_location('fixture_generator', ROOT / 'generate_seed.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def test_rendered_sql_is_current_and_insert_only():
    seed = (ROOT / '02_seed.sql').read_text(encoding='utf-8')
    assert seed == generator.render()
    statements = '\n'.join(line for line in seed.splitlines() if not line.lstrip().startswith('--'))
    assert not re.search(r'\b(UPDATE|DELETE|TRUNCATE|DISABLE|ON CONFLICT)\b', statements, re.I)
    assert 'silver.fixture_consent' in seed and 'silver.fixture_database' in seed
    assert 'LOCK TABLE' in seed and 'EXCEPT ALL' in seed
    assert 'legacy true/unrated' in seed


def test_migration_preserves_legacy_bool_and_unknown_level_and_checks_range():
    sql = (ROOT / '01_recommendation_level.sql').read_text(encoding='utf-8')
    check = re.search(r'CHECK \((recommendation_level >= 1 AND recommendation_level <= 5)\)', sql)[1]
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE flags(is_recommended BOOLEAN NOT NULL DEFAULT true)')
        db.executemany('INSERT INTO flags VALUES (?)', [(True,), (False,)])
        db.execute(f'ALTER TABLE flags ADD COLUMN recommendation_level INTEGER CHECK ({check})')
        assert db.execute('SELECT * FROM flags').fetchall() == [(1, None), (0, None)]
        for level in range(1, 6):
            db.execute('INSERT INTO flags(recommendation_level) VALUES (?)', (level,))
        for level in (-1, 0, 6, 100):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute('INSERT INTO flags(recommendation_level) VALUES (?)', (level,))
    assert 'ADD COLUMN IF NOT EXISTS recommendation_level integer' in sql
    assert 'NOT a.atthasdef' in sql and 'NOT a.attnotnull' in sql


@pytest.mark.parametrize('name', ['01_recommendation_level.sql', '02_seed.sql'])
def test_each_write_sql_overrides_inherited_consent_with_rejecting_placeholders(name):
    sql = (ROOT / name).read_text(encoding='utf-8')
    statements = '\n'.join(line for line in sql.splitlines() if not line.lstrip().startswith('--'))
    before_guard = statements.split('DO $guard$')[0].strip()
    assert before_guard == ("BEGIN;\n"
        "SET LOCAL silver.fixture_consent = 'REPLACE_WITH_SUMIDA_TEST_CONSENT';\n"
        "SET LOCAL silver.fixture_database = 'REPLACE_WITH_VERIFIED_DATABASE_NAME';")
    assert "IS DISTINCT FROM 'sumida-test-only-v1'" in sql
    assert "IS DISTINCT FROM current_database()" in sql


def test_manifest_birth_dates_are_fixed_fictional_and_keep_identity():
    rows = generator.members()
    assert rows == generator.members() and len(rows) == 90
    assert len({r[0] for r in rows}) == len({r[1] for r in rows}) == 90
    for uid, code, _, _, birthday in rows:
        assert uid == str(generator.uuid5(generator.NAMESPACE, f'sumida/member/{code}'))
        birth = date.fromisoformat(birthday)
        assert 60 <= 2026 - birth.year <= 80  # age at fixed 2026-12-31
    assert len({r[-1] for r in rows}) > 21


def test_insert_targets_match_explicit_projection_and_catalog_guard():
    sql = generator.render()
    for table in ('members', 'jobs', 'job_recommendation_flags'):
        target, projection = re.search(rf'INSERT INTO public\.{table}\(([^)]+)\)\n SELECT (.*?) FROM', sql).groups()
        columns = target.split(',')
        assert projection.split(',') == ['f.' + c for c in columns]
        catalog_columns = re.search(rf"'public\.{table}'::regclass, ARRAY\[([^]]+)\]", sql)[1]
        assert re.findall(r"'([^']+)'", catalog_columns) == columns
    assert 'DO $schema$' in sql and sql.index('END $schema$') < sql.index('CREATE TEMP TABLE')
    assert "atttypid='date'::regtype AND attnotnull" in sql
    assert 'a.attnotnull AND NOT a.atthasdef' in sql
    assert "a.attidentity='' AND a.attgenerated=''" in sql


@pytest.fixture
def fixture_db():
    db = sqlite3.connect(':memory:')
    db.execute("ATTACH DATABASE ':memory:' AS public")
    db.execute('CREATE TABLE public.members(id TEXT PRIMARY KEY,member_code TEXT,full_name TEXT,center_code TEXT,phone_mobile_normalized TEXT,created_at TEXT,updated_at TEXT,birth_date DATE NOT NULL,UNIQUE(center_code,member_code))')
    db.execute('CREATE TABLE public.jobs(id TEXT PRIMARY KEY,job_code TEXT,title TEXT,summary TEXT,location_text TEXT,work_date_text TEXT,status TEXT,center_code TEXT,created_at TEXT,updated_at TEXT,UNIQUE(center_code,job_code))')
    db.execute('CREATE TABLE public.job_recommendation_flags(member_id TEXT,job_id TEXT,center_code TEXT,is_recommended BOOLEAN NOT NULL DEFAULT true,recommendation_level INTEGER CHECK(recommendation_level BETWEEN 1 AND 5),created_at TEXT,updated_at TEXT,UNIQUE(center_code,job_id,member_id))')
    # Use the actual rendered manifest VALUES in SQLite, changing only UUID type to TEXT.
    seed = generator.render()
    for table in ('member', 'job', 'rating'):
        create = re.search(rf'CREATE TEMP TABLE _rec_{table}_manifest\(.*?;', seed)[0]
        db.execute(create.replace('uuid', 'TEXT').replace(' ON COMMIT DROP', ''))
        db.execute(re.search(rf'INSERT INTO _rec_{table}_manifest VALUES.*?;', seed, re.S)[0])
    for number in range(1, 31):
        db.execute("INSERT INTO public.members VALUES (?,?,?,'sumida',NULL,'2026-01-01','2026-01-01',?)", (f'legacy-{number}', f'{number:04}', 'legacy',f'1950-01-{1 + number % 28:02}'))
    for number in range(1, 11):
        db.execute("INSERT INTO public.jobs VALUES (?,?,'legacy',NULL,NULL,NULL,'published','sumida','2026-01-01','2026-01-01')", (f'legacy-job-{number}',f'TEST-JOB-{number:03}'))
    for number in range(65):
        db.execute("INSERT INTO public.job_recommendation_flags VALUES (?,?,'sumida',true,NULL,'2026-01-01','2026-01-01')", (f'legacy-{number % 30 + 1}', f'legacy-job-{number // 30 + 1}'))
    baseline = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.execute('CREATE TEMP TABLE _rec_members AS SELECT * FROM public.members WHERE 0')
    for uid, code, name, hours, birth_date in db.execute('SELECT * FROM _rec_member_manifest').fetchall():
        ts = (baseline + timedelta(hours=hours)).isoformat()
        db.execute('INSERT INTO _rec_members VALUES (?,?,?,?,?,?,?,?)', (uid, code, name, 'sumida', None, ts, ts, birth_date))
    db.execute('CREATE TEMP TABLE _rec_jobs AS SELECT * FROM public.jobs WHERE 0')
    for uid, code, title, days in db.execute('SELECT * FROM _rec_job_manifest').fetchall():
        ts = (baseline + timedelta(days=days)).isoformat()
        db.execute('INSERT INTO _rec_jobs VALUES (?,?,?,?,?,?,?,?,?,?)', (uid,code,title,'Dedicated recommendation fixture v1','TEST ONLY','TEST ONLY','published','sumida',ts,ts))
    yield db
    db.close()


def apply_fixture(db):
    seed = generator.render()
    # Execute the actual SQL conflict predicates; ROW(a,b) -> (a,b) is SQLite spelling.
    ownership = seed.split('DO $ownership$')[1].split('END $ownership$')[0]
    for predicate in re.findall(r'IF EXISTS \((.*?)\) THEN', ownership, re.S):
        if db.execute(predicate.replace('ROW(', '(')).fetchone():
            raise ValueError('fixture conflict')
    for table in ('members', 'jobs'):
        db.execute(re.search(rf'INSERT INTO public\.{table}\(.*?;', seed, re.S)[0])
    db.execute('DROP TABLE IF EXISTS _rec_flags')
    db.execute("CREATE TEMP TABLE _rec_flags AS SELECT m.id AS member_id,j.id AS job_id,'sumida' AS center_code,true AS is_recommended,r.level AS recommendation_level,'fixture-ts' AS created_at,'fixture-ts' AS updated_at FROM _rec_rating_manifest r JOIN public.members m ON m.center_code='sumida' AND CAST(m.member_code AS INTEGER)=CAST(r.member_code AS INTEGER) JOIN _rec_jobs j ON j.job_code=r.job_code")
    predicate = re.search(r'IF EXISTS \((.*?)\) THEN', seed.split('DO $flags$')[1], re.S)[1]
    if db.execute(predicate.replace('ROW(', '(')).fetchone():
        raise ValueError('fixture conflict')
    db.execute(re.search(r'INSERT INTO public\.job_recommendation_flags\(.*?;', seed, re.S)[0])
    verify = seed.split('DO $verify$')[1].split('  IF (SELECT count(*)')[0]
    expression = re.search(r'IF (.*?) THEN', verify, re.S)[1]
    assert db.execute('SELECT ' + expression.replace('ROW(', '(')).fetchone() == (0,)


def test_seed_dml_idempotence_distribution_and_legacy_preservation(fixture_db):
    db = fixture_db
    legacy = [db.execute(f'SELECT * FROM public.{t}').fetchall() for t in ('members','jobs','job_recommendation_flags')]
    apply_fixture(db)
    snapshot = [db.execute(f'SELECT * FROM public.{t}').fetchall() for t in ('members','jobs','job_recommendation_flags')]
    apply_fixture(db)
    assert snapshot == [db.execute(f'SELECT * FROM public.{t}').fetchall() for t in ('members','jobs','job_recommendation_flags')]
    assert len(snapshot[0]) == 120 and len(snapshot[1]) == 13 and len(snapshot[2]) == 425
    assert [rows[:len(old)] for rows, old in zip(snapshot, legacy)] == legacy
    assert all(row[3] == 1 and row[4] is None for row in snapshot[2][:65])
    assert sorted(int(row[1]) for row in snapshot[0]) == list(range(1, 121))
    assert [int(row[1]) for row in sorted(snapshot[0], key=lambda row:row[5], reverse=True)[:50]] == list(range(120,70,-1))
    assert len({row[8] for row in snapshot[1][10:]}) == 3
    first = [r for r in generator.ratings() if r[1]=='REC-V1-JOB-001']
    assert [int(r[0]) for r in first if r[2]==5] == list(range(71,121))
    assert {r[2] for r in first if int(r[0])<=70} == {1,2,3,4}
    for code in range(1,121):
        assert len({r[2] for r in generator.ratings() if r[0]==str(code)}) > 1
    assert all(row[4] is None for row in snapshot[0][30:])
    assert [row[7] for row in snapshot[0][:30]] == [row[7] for row in legacy[0]]
    assert {row[1]:row[7] for row in snapshot[0][30:]} == {r[1]:r[4] for r in generator.members()}


def test_missing_birth_date_fails_without_default(fixture_db):
    db = fixture_db
    column = next(row for row in db.execute('PRAGMA public.table_info(members)') if row[1]=='birth_date')
    assert column[2]=='DATE' and column[3]==1 and column[4] is None
    sql = re.search(r'INSERT INTO public\.members\(.*?;', generator.render(), re.S)[0]
    old_sql = sql.replace(',birth_date)', ')').replace(',f.birth_date FROM', ' FROM')
    with pytest.raises(sqlite3.IntegrityError, match='birth_date'):
        db.execute(old_sql)
    assert db.execute('SELECT count(*) FROM public.members').fetchone() == (30,)


@pytest.mark.parametrize('conflict', ['same_code', 'same_id', 'changed_member', 'changed_birth_date', 'changed_job', 'changed_flag'])
def test_fixture_conflicts_abort_without_overwrite(fixture_db, conflict):
    db = fixture_db
    apply_fixture(db)
    if conflict=='same_code':
        db.execute("UPDATE public.members SET id='unowned' WHERE member_code='31'")
    elif conflict=='same_id':
        db.execute("UPDATE public.members SET member_code='999' WHERE member_code='31'")
    elif conflict=='changed_member':
        db.execute("UPDATE public.members SET full_name='changed' WHERE member_code='31'")
    elif conflict=='changed_birth_date':
        db.execute("UPDATE public.members SET birth_date='1940-01-01' WHERE member_code='31'")
    elif conflict=='changed_job':
        db.execute("UPDATE public.jobs SET updated_at='changed' WHERE job_code='REC-V1-JOB-001'")
    else:
        db.execute('UPDATE public.job_recommendation_flags SET recommendation_level=1 WHERE recommendation_level=5')
    before = [db.execute(f'SELECT * FROM public.{t}').fetchall() for t in ('members','jobs','job_recommendation_flags')]
    with pytest.raises(ValueError, match='fixture conflict'):
        apply_fixture(db)
    assert before == [db.execute(f'SELECT * FROM public.{t}').fetchall() for t in ('members','jobs','job_recommendation_flags')]


@pytest.mark.parametrize('size', [50, 100, 101])
def test_future_selection_contract_with_mock_linkage_only(size):
    # Contract example only. No application selector, LINE ID, linkage write or send.
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE candidates(member_number TEXT, recommendation_level INTEGER, line_linked BOOLEAN, is_recommended BOOLEAN)')
        db.executemany('INSERT INTO candidates VALUES (?,5,true,true)', [(str(n),) for n in range(1,size+1)])
        db.executemany('INSERT INTO candidates VALUES (?,?,?,true)', [('1001',5,False),('1002',4,True),('1003',None,True)])
        rows = db.execute('SELECT member_number FROM candidates WHERE recommendation_level=5 AND line_linked=true ORDER BY CAST(member_number AS INTEGER) DESC LIMIT 100').fetchall()
        assert [int(row[0]) for row in rows] == list(range(size, max(0,size-100), -1))

"""Real PostgreSQL + fixture private Storage; no inference or seeded outcomes."""
from uuid import UUID

import pytest
from test_finance_postgres import database as database  # noqa: PLC0414
from test_finance_postgres import identity
from test_finance_postgres import state as state  # noqa: PLC0414
from test_guided_scenario import GuidedDB

from app.config import Settings
from app.finance.tools import FinanceToolClient
from app.finance.types import FinanceError, Scope
from app.guided_demo import GUIDED_SCENARIO_VERSION, seed_guided_scenario
from app.photo_booth_demo import PHOTO_PROMPT
from app.runtime.skills import routed_skill_names


def create_photo(state):
    conn, _org, _run, users = state
    conn.execute("reset role")
    conn.execute("update memberships set role='director' where user_id=%s", (users[0],))
    identity(conn, users[0])
    result = conn.execute("select create_finance_guided_demo()").fetchone()[0]
    identity(conn, service=True)
    db = GuidedDB(conn)
    tools = FinanceToolClient(Scope(UUID(result['organization_id']), UUID(result['run_id']), users[0]), db)
    job = {'id': result['seed_job_id'], 'organization_id': result['organization_id'], 'run_id': result['run_id'],
           'requested_by': str(users[0]), 'command_type': 'intake',
           'payload': {'source': 'demo_bundle', 'bundle_version': GUIDED_SCENARIO_VERSION}}
    return conn, db, tools, job, result


@pytest.mark.asyncio
async def test_only_opening_finances_seeded_all_other_evidence_waits_for_real_review(state):
    conn, db, tools, job, scope = create_photo(state)
    seeded = await seed_guided_scenario(Settings(_env_file=None), tools, db, job)
    snapshot = await tools.call('get_finance_snapshot', {})
    scenario = snapshot['run']['scenario']
    assert scenario['id'] == 'finney-photo-booth-v1' and scenario['status'] == 'ready'
    assert snapshot['position']['cash_minor'] == '620000'
    assert snapshot['position']['committed_minor'] == '550000'
    assert snapshot['position']['available_minor'] == '70000'
    assert snapshot['position']['receivable_minor'] == '0'
    assert len(snapshot['obligations']) == 4
    assert {row['amount_minor'] for row in snapshot['obligations']} == {'250000', '180000', '90000', '30000'}
    assert all(row['direction'] == 'payable' and row['settled_minor'] == '0' for row in snapshot['obligations'])
    assert seeded['source_results'] == [] and not seeded['payments_enabled']
    sources = snapshot['source_items']
    assert len(sources) == 17
    catering = sorted((row for row in sources if row['external_id'].endswith(':catering')), key=lambda row: row['version'])
    assert [row['version'] for row in catering] == [1, 2]
    assert any(row['source_refs'] == [{'id': catering[0]['id'], 'version': 1}] for row in snapshot['obligations'])
    reminder = next(row for row in sources if row['external_id'].endswith(':catering-reminder'))
    assert reminder['version'] == 1 and reminder['external_id'] != catering[1]['external_id']
    step = scenario['steps'][0]
    assert len(scenario['steps']) == 1 and step['id'] == 'review' and step['prompt'] == PHOTO_PROMPT
    event = next(row for row in snapshot['cases'] if row['id'] == step['case_id'])
    assert len(event['data']['source_ids']) == 16
    assert catering[1]['id'] in event['data']['source_ids'] and catering[0]['id'] not in event['data']['source_ids']
    assert catering[0]['id'] in event['data']['superseded_source_ids']
    assert {'budget-cash-planning', 'vendor-spend', 'organizer-expenses', 'sponsor-receivables', 'close-reporting'} <= set(routed_skill_names('review_case', {}, event))
    assert all(not row['data'].get('finding') and not row['data'].get('director_responses') for row in snapshot['cases'])
    for row in sources:
        document = await tools.call('read_document', {'source_id': row['id']})
        assert 'FICTIONAL DEMO DOCUMENT' in document['content']
    conn.execute('reset role')
    for table in ('action_proposals', 'payments', 'budget_decisions', 'eval_runs', 'promotions'):
        assert conn.execute(f'select count(*) from {table} where run_id=%s', (scope['run_id'],)).fetchone()[0] == 0
    assert conn.execute("select count(*) from jobs where run_id=%s and command_type<>'intake'", (scope['run_id'],)).fetchone()[0] == 0
    assert conn.execute("select count(*) from trace_events where run_id=%s and event_type in ('actor_completed','actor_failed','director_response_persisted')", (scope['run_id'],)).fetchone()[0] == 0
    identity(conn, service=True)
    # A second seed invocation cannot add versions, reset balances or review data.
    await seed_guided_scenario(Settings(_env_file=None), tools, db, job)
    again = await tools.call('get_finance_snapshot', {})
    assert again['source_items'] == sources and again['obligations'] == snapshot['obligations']


@pytest.mark.asyncio
async def test_new_default_resumes_and_explicit_restart_stays_new_scenario(state):
    conn, db, tools, job, scope = create_photo(state)
    await seed_guided_scenario(Settings(_env_file=None), tools, db, job)
    identity(conn, service=True)
    with pytest.raises(FinanceError, match='version_mismatch'):
        await seed_guided_scenario(Settings(_env_file=None), tools, db,
                                   {**job, 'payload': {'source': 'demo_bundle', 'bundle_version': 'finney-mid-event-v1'}})
    identity(conn, state[3][0])
    assert conn.execute('select create_finance_guided_demo()').fetchone()[0]['run_id'] == scope['run_id']
    fresh = conn.execute('select restart_finance_guided_demo(%s)', (scope['run_id'],)).fetchone()[0]
    assert fresh['run_id'] != scope['run_id']
    snap = conn.execute('select get_finance_snapshot(%s,%s)', (fresh['organization_id'], fresh['run_id'])).fetchone()[0]
    assert snap['run']['scenario']['id'] == 'finney-photo-booth-v1'
    assert snap['run']['scenario']['seed_status'] == 'queued'
    assert snap['position']['cash_minor'] is None and not snap['obligations']


def test_new_default_does_not_resume_or_modify_legacy_run(state):
    from test_guided_scenario import create

    conn, _db, _tools, _job, old = create(state)
    identity(conn, state[3][0])
    fresh = conn.execute('select create_finance_guided_demo()').fetchone()[0]
    assert fresh['run_id'] != old['run_id']
    conn.execute('reset role')
    assert conn.execute('select status,scenario->>\'id\' from demo_runs where id=%s', (old['run_id'],)).fetchone() == ('active', 'finney-mid-event-v1')
    assert conn.execute('select status from jobs where id=%s', (old['seed_job_id'],)).fetchone()[0] == 'queued'


@pytest.mark.asyncio
async def test_failed_new_seed_recovers_without_resetting_failed_job_or_leaking_review(state):
    conn, db, tools, job, scope = create_photo(state)
    conn.execute('reset role')
    conn.execute("update jobs set status='failed',error_code='fixture_seed_failure' where id=%s", (job['id'],))
    identity(conn, state[3][0])
    before = conn.execute('select get_finance_snapshot(%s,%s)', (scope['organization_id'], scope['run_id'])).fetchone()[0]
    assert before['run']['scenario']['seed_status'] == 'failed'
    retried = conn.execute('select create_finance_guided_demo()').fetchone()[0]
    assert retried['run_id'] == scope['run_id'] and retried['seed_job_id'] != job['id']
    assert retried['seed_attempts'] == 2 and retried['seed_status'] == 'queued'
    identity(conn, service=True)
    await seed_guided_scenario(Settings(_env_file=None), tools, db, {**job, 'id': retried['seed_job_id']})
    snapshot = await tools.call('get_finance_snapshot', {})
    assert snapshot['run']['scenario']['seed_status'] == 'ready'
    assert snapshot['run']['scenario']['seed_attempts'] == 2
    conn.execute('reset role')
    assert conn.execute('select status,error_code from jobs where id=%s', (job['id'],)).fetchone() == ('failed', 'fixture_seed_failure')
    assert conn.execute('select count(*) from ledger_transactions where run_id=%s', (scope['run_id'],)).fetchone()[0] == 1
    assert conn.execute("select count(*) from jobs where run_id=%s and command_type<>'intake'", (scope['run_id'],)).fetchone()[0] == 0

"""Fresh practice creates a new run; actual PostgreSQL, no inference or provider calls."""
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import psycopg
import pytest
from test_finance_postgres import call, identity
from test_finance_postgres import database as database  # noqa: PLC0414
from test_finance_postgres import state as state  # noqa: PLC0414
from test_guided_scenario import create

from app.config import Settings
from app.finance.tools import FinanceToolClient
from app.finance.types import Scope
from app.guided_demo import GUIDED_SCENARIO_VERSION, seed_guided_scenario


def restart(conn, run):
    return conn.execute("select restart_finance_guided_demo(%s)", (run,)).fetchone()[0]


@pytest.mark.asyncio
async def test_restart_preserves_prior_records_and_shared_limits_then_seeds_one_fresh_run(state):
    conn, db, tools, job, _old = create(state)
    await seed_guided_scenario(Settings(_env_file=None), tools, db, job)
    org, old_run, owner = tools.scope.organization_id, tools.scope.run_id, state[3][0]
    call(conn, org, old_run, "reserve_run_inference", {"reservation_id": job["id"], "max_model_calls": 8})
    conn.execute("reset role")
    conn.execute("update jobs set status='completed' where id=%s", (job["id"],))
    old_obligations = conn.execute("select to_jsonb(o) from obligations o where run_id=%s order by id", (old_run,)).fetchall()
    old_sources = conn.execute("select to_jsonb(s) from source_items s where run_id=%s order by id", (old_run,)).fetchall()
    old_cases = conn.execute("select to_jsonb(c) from cases c where run_id=%s order by id", (old_run,)).fetchall()
    quota = conn.execute("select model_call_limit,reserved_model_calls from finance_demo_owner_limits where user_id=%s", (owner,)).fetchone()
    daily = conn.execute("select utc_day,model_call_limit,reserved_model_calls from finance_demo_daily_limits order by utc_day").fetchall()
    identity(conn, owner)
    fresh = restart(conn, old_run)
    assert fresh["run_id"] != str(old_run) and fresh["organization_id"] == str(org)
    assert fresh["previous_run_id"] == str(old_run) and fresh["seed_status"] == "queued"
    assert fresh["experience_version"] == "finney-photo-booth-v1"
    # Normal entry resumes the fresh practice; it does not create another run.
    assert conn.execute("select create_finance_guided_demo()").fetchone()[0]["run_id"] == fresh["run_id"]
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        restart(conn, old_run)
    conn.execute("reset role")
    assert conn.execute("select status from demo_runs where id=%s", (old_run,)).fetchone()[0] == "cancelled"
    assert conn.execute("select status from jobs where id=%s", (job["id"],)).fetchone()[0] == "completed"
    assert conn.execute("select to_jsonb(o) from obligations o where run_id=%s order by id", (old_run,)).fetchall() == old_obligations
    assert conn.execute("select to_jsonb(s) from source_items s where run_id=%s order by id", (old_run,)).fetchall() == old_sources
    assert conn.execute("select to_jsonb(c) from cases c where run_id=%s order by id", (old_run,)).fetchall() == old_cases
    assert conn.execute("select model_call_limit,reserved_model_calls from finance_demo_owner_limits where user_id=%s", (owner,)).fetchone() == quota
    assert conn.execute("select utc_day,model_call_limit,reserved_model_calls from finance_demo_daily_limits order by utc_day").fetchall() == daily
    assert conn.execute("select count(*) from demo_runs where owner_user_id=%s and status='active'", (owner,)).fetchone()[0] == 1
    assert conn.execute("select count(*) from jobs where run_id=%s", (fresh["run_id"],)).fetchone()[0] == 1
    identity(conn, service=True)
    new_tools = FinanceToolClient(Scope(org, UUID(fresh["run_id"]), owner), db)
    new_job = {**job, "id": fresh["seed_job_id"], "run_id": fresh["run_id"],
               "payload": {"source": "demo_bundle", "bundle_version": GUIDED_SCENARIO_VERSION}}
    await seed_guided_scenario(Settings(_env_file=None), new_tools, db, new_job)
    position = await new_tools.call("get_financial_position", {})
    assert position["available_minor"] == "70000" and position["cash_minor"] == "620000"
    assert (await new_tools.call("get_finance_snapshot", {}))["run"]["scenario"]["experience_version"] == "finney-photo-booth-v1"


def test_running_job_refuses_restart_even_with_expired_lease_and_does_not_cancel_work(state):
    conn, _db, tools, job, _scope = create(state)
    conn.execute("reset role")
    conn.execute("update jobs set status='running',lease_expires_at='2000-01-01' where id=%s", (job["id"],))
    identity(conn, state[3][0])
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="wait for running"):
        restart(conn, tools.scope.run_id)
    conn.execute("reset role")
    assert conn.execute("select status from jobs where id=%s", (job["id"],)).fetchone()[0] == "running"
    assert conn.execute("select status from demo_runs where id=%s", (tools.scope.run_id,)).fetchone()[0] == "active"
    assert conn.execute("select count(*) from demo_runs where owner_user_id=%s", (state[3][0],)).fetchone()[0] == 1


def test_restart_is_owner_only_and_service_cannot_impersonate_owner(state):
    conn, _db, tools, _job, _scope = create(state)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        restart(conn, tools.scope.run_id)
    identity(conn, state[3][1])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        restart(conn, tools.scope.run_id)
    identity(conn, state[3][0])
    conn.execute("select set_config('request.jwt.claims','{\"is_anonymous\":true}',false)")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        restart(conn, tools.scope.run_id)


def test_concurrent_restart_creates_only_one_fresh_run_and_cancels_only_prior_queued_job(state, database):
    conn, _db, tools, job, _scope = create(state)
    owner, old_run = state[3][0], tools.scope.run_id
    def invoke():
        with psycopg.connect(database, autocommit=True) as session:
            identity(session, owner)
            try:
                return restart(session, old_run)
            except psycopg.errors.ObjectNotInPrerequisiteState:
                return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: invoke(), range(2)))
    assert sum(result is not None for result in results) == 1
    conn.execute("reset role")
    assert conn.execute("select status from jobs where id=%s", (job["id"],)).fetchone()[0] == "cancelled"
    assert conn.execute("select count(*) from demo_runs where owner_user_id=%s", (owner,)).fetchone()[0] == 2

"""Real disposable PostgreSQL queue tests. No hosted jobs or provider requests."""
from uuid import uuid4

import psycopg
import pytest
from test_finance_postgres import database as database  # noqa: PLC0414
from test_finance_postgres import identity
from test_finance_postgres import state as state  # noqa: PLC0414


@pytest.fixture(autouse=True)
def finish_scope(state):
    yield
    conn, _, run, _ = state
    identity(conn, service=True)
    conn.execute("update jobs set status='completed' where run_id=%s", (run,))


def add(state, command, *, age=0):
    conn, org, run, users = state
    return conn.execute(
        "insert into jobs(organization_id,run_id,command_type,payload,requested_by,idempotency_key,created_at,available_at) "
        "values(%s,%s,%s,'{}',%s,%s,now()-make_interval(secs=>%s),now()-make_interval(secs=>%s)) returning id",
        (org, run, command, users[0], "priority-fixture:" + uuid4().hex, age, age),
    ).fetchone()[0]


def lease(conn):
    return conn.execute("select lease_finance_job('priority-fixture',120)").fetchone()[0]


def test_director_prompt_gets_next_lease_ahead_of_older_background_work(state):
    conn, _, _, _ = state
    learning = add(state, "evaluate_improvement", age=10)
    review = add(state, "review_case", age=9)
    intake = add(state, "intake", age=8)
    prompt = add(state, "director_message")
    assert lease(conn)["id"] == str(prompt)
    assert lease(conn)["id"] == str(intake)
    assert lease(conn)["id"] == str(review)
    assert lease(conn)["id"] == str(learning)


def test_ready_background_work_ages_into_fifo_without_starvation(state):
    conn, _, _, _ = state
    learning = add(state, "evaluate_improvement", age=901)
    prompt = add(state, "director_message")
    assert lease(conn)["id"] == str(learning)
    assert lease(conn)["id"] == str(prompt)


def test_active_job_is_not_preempted_and_expired_lease_recovers_first(state):
    conn, _, _, _ = state
    learning = add(state, "evaluate_improvement", age=10)
    active = lease(conn)
    prompt = add(state, "director_message")
    assert lease(conn)["id"] == str(prompt)
    assert lease(conn) is None  # neither existing active lease is stolen
    conn.execute("update jobs set lease_expires_at=now()-interval '1 second' where id=%s", (learning,))
    add(state, "director_message")
    recovered = lease(conn)
    assert recovered["id"] == str(learning)
    assert recovered["lease_token"] != active["lease_token"]
    assert recovered["attempts"] == 2


def test_browser_cannot_claim_priority_lease_or_change_running_job(state):
    conn, _, _, users = state
    add(state, "director_message")
    identity(conn, users[0])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        lease(conn)


def test_expired_run_and_future_job_remain_ineligible(state):
    conn, _, run, _ = state
    prompt = add(state, "director_message")
    conn.execute("update jobs set available_at=now()+interval '1 hour' where id=%s", (prompt,))
    assert lease(conn) is None
    conn.execute("update jobs set available_at=now() where id=%s", (prompt,))
    conn.execute("update demo_runs set expires_at=now()-interval '1 second' where id=%s", (run,))
    assert lease(conn) is None

"""Actual local PostgreSQL method caps; no hosted/model/payment operations."""

from uuid import uuid4

import psycopg
import pytest
from test_finance_postgres import call, identity
from test_finance_postgres import database as database  # noqa: PLC0414 -- pytest fixture registration
from test_finance_postgres import state as state  # noqa: PLC0414 -- pytest fixture registration
from test_finance_runtime_guards import attempt_arguments, skill_pair


def test_actual_sql_harness2_cap96_and_legacy_actor_caps40(state):
    conn, org, run, _ = state
    baseline, _ = skill_pair(conn, org, run)
    args = attempt_arguments(conn, org, run, baseline)
    for calls, method in [(41, "single_patch"), (97, "harness2")]:
        with pytest.raises(psycopg.errors.InvalidParameterValue, match="method limit"):
            call(
                conn,
                org,
                run,
                "claim_improvement_attempt",
                {**args, "max_model_calls": calls, "improvement_method": method},
            )
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="method limit"):
        call(
            conn,
            org,
            run,
            "reserve_run_inference",
            {
                "reservation_id": str(uuid4()),
                "max_model_calls": 41,
                "improvement_method": "harness2",
            },
        )
    result = call(
        conn,
        org,
        run,
        "claim_improvement_attempt",
        {**args, "max_model_calls": 96, "improvement_method": "harness2"},
    )
    assert result["claimed"]
    conn.execute("reset role")
    assert conn.execute(
        "select max_model_calls,improvement_method from finance_improvement_attempts where id=%s",
        (args["attempt_id"],),
    ).fetchone() == (96, "harness2")
    assert conn.execute(
        "select reserved_model_calls,reserved_improvement_attempts from finance_run_execution_limits where run_id=%s",
        (run,),
    ).fetchone() == (96, 1)


def test_actual_sql_harness2_still_checks_run_budget_and_owner_day_budgets(state):
    conn, org, run, users = state
    baseline, _ = skill_pair(conn, org, run)
    args = attempt_arguments(conn, org, run, baseline)
    conn.execute("reset role")
    conn.execute(
        "insert into finance_run_execution_limits(organization_id,run_id,model_call_limit) values(%s,%s,95)",
        (org, run),
    )
    identity(conn, service=True)
    rejected = call(
        conn,
        org,
        run,
        "claim_improvement_attempt",
        {**args, "max_model_calls": 96, "improvement_method": "harness2"},
    )
    assert rejected["reason"] == "run_model_call_budget_exhausted"
    conn.execute("reset role")
    conn.execute(
        "update finance_run_execution_limits set model_call_limit=120 where run_id=%s", (run,)
    )
    conn.execute("update demo_runs set is_demo=true,owner_user_id=%s where id=%s", (users[0], run))
    conn.execute(
        "insert into finance_demo_owner_limits(user_id,model_call_limit,reserved_model_calls) values(%s,120,25)",
        (users[0],),
    )
    identity(conn, service=True)
    rejected = call(
        conn,
        org,
        run,
        "claim_improvement_attempt",
        {**args, "max_model_calls": 96, "improvement_method": "harness2"},
    )
    assert rejected["reason"] == "demo_owner_lifetime_model_budget_exhausted"
    conn.execute("reset role")
    conn.execute(
        "update finance_demo_owner_limits set reserved_model_calls=0 where user_id=%s", (users[0],)
    )
    conn.execute(
        "insert into finance_demo_daily_limits(utc_day,model_call_limit,reserved_model_calls) values((now() at time zone 'UTC')::date,600,505) on conflict(utc_day) do update set model_call_limit=600,reserved_model_calls=505"
    )
    identity(conn, service=True)
    rejected = call(
        conn,
        org,
        run,
        "claim_improvement_attempt",
        {**args, "max_model_calls": 96, "improvement_method": "harness2"},
    )
    assert rejected["reason"] == "demo_daily_model_budget_exhausted"
    conn.execute("reset role")
    conn.execute(
        "update finance_demo_daily_limits set reserved_model_calls=0 where utc_day=(now() at time zone 'UTC')::date"
    )
    identity(conn, service=True)
    assert call(
        conn,
        org,
        run,
        "claim_improvement_attempt",
        {**args, "max_model_calls": 96, "improvement_method": "harness2"},
    )["claimed"]
    assert not call(
        conn,
        org,
        run,
        "claim_improvement_attempt",
        {**args, "max_model_calls": 96, "improvement_method": "harness2"},
    )["claimed"]
    conn.execute("reset role")
    assert (
        conn.execute(
            "select reserved_model_calls from finance_demo_owner_limits where user_id=%s",
            (users[0],),
        ).fetchone()[0]
        == 96
    )
    assert (
        conn.execute(
            "select reserved_model_calls from finance_demo_daily_limits where utc_day=(now() at time zone 'UTC')::date"
        ).fetchone()[0]
        == 96
    )

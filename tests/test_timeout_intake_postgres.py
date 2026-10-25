"""Actual disposable PostgreSQL timeout admission; all identities/data are fixtures."""
from uuid import uuid4

import psycopg
import pytest
from test_failed_trace_postgres import failed_attempt, record_failure
from test_finance_postgres import call
from test_finance_postgres import database as database  # noqa: PLC0414 -- fixture registration
from test_finance_postgres import state as state  # noqa: PLC0414 -- fixture registration


def timeout_attempt(conn, org, run):
    args, payload = failed_attempt(conn, org, run)
    payload["failure_observations"].update(reason="opencode_timeout", api_calls=0)
    return args, payload


def test_zero_call_timeout_keeps_original_reservation_and_normal_attempt_limits(state):
    conn, org, run, _ = state
    args, payload = timeout_attempt(conn, org, run)
    args = record_failure(conn, org, run, args, payload)
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="method limit"):
        call(conn, org, run, "claim_improvement_attempt", {**args, "max_model_calls": 41})
    assert call(conn, org, run, "claim_improvement_attempt", args)["claimed"]
    assert call(conn, org, run, "claim_improvement_attempt", {**args, "attempt_id": str(uuid4())})["reason"] == "improvement_attempt_already_claimed"
    conn.execute("reset role")
    assert conn.execute("select reserved_model_calls,reserved_improvement_attempts from finance_run_execution_limits where run_id=%s", (run,)).fetchone() == (49, 1)
    assert conn.execute("select count(*) from finance_improvement_attempts where run_id=%s", (run,)).fetchone()[0] == 1
    for table in ["obligations", "action_proposals", "payments", "promotions", "finance_improvement_holdouts"]:
        assert conn.execute(f"select count(*) from {table} where run_id=%s", (run,)).fetchone()[0] == 0


@pytest.mark.parametrize("mutation", ["output", "wrong_job", "no_reservation", "bad_context_hash", "wrong_scope", "ineligible", "unknown_reason", "wrong_contract"])
def test_timeout_still_rejects_forged_provenance_or_financial_output(state, mutation):
    conn, org, run, _ = state
    args, payload = timeout_attempt(conn, org, run)
    if mutation == "output": payload["output"] = {"decision": "pay_vendor"}
    elif mutation == "wrong_job": payload["job_id"] = str(uuid4())
    elif mutation == "no_reservation": payload["inference_reservation"]["reservation_id"] = str(uuid4())
    elif mutation == "bad_context_hash": payload["context_sha256"] = "bad"
    elif mutation == "wrong_scope": payload["diagnostic_artifact"]["artifact_path"] = f"{org}/{uuid4()}/artifacts/foreign"
    elif mutation == "ineligible": payload["improvement_eligible"] = False
    elif mutation == "unknown_reason": payload["failure_observations"]["reason"] = "opencode_unknown_failure"
    elif mutation == "wrong_contract": payload["failure_observations"]["contract"] = "untrusted"
    args = record_failure(conn, org, run, args, payload)
    with pytest.raises(psycopg.errors.CheckViolation):
        call(conn, org, run, "claim_improvement_attempt", args)
    conn.execute("reset role")
    assert conn.execute("select reserved_model_calls,reserved_improvement_attempts from finance_run_execution_limits where run_id=%s", (run,)).fetchone() == (9, 0)

"""Actual isolated PostgreSQL guard checks; no hosted/provider/model calls."""
import copy
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_finance_postgres import call
from test_finance_postgres import database as database  # noqa: PLC0414 -- pytest fixture registration
from test_finance_postgres import state as state  # noqa: PLC0414 -- pytest fixture registration
from test_finance_runtime_guards import attempt_arguments, skill_pair


def failed_attempt(conn, org, run):
    baseline, _ = skill_pair(conn, org, run)
    args = attempt_arguments(conn, org, run, baseline)
    job_id = str(uuid4())
    conn.execute("insert into jobs(id,organization_id,run_id,command_type,payload,idempotency_key) values(%s,%s,%s,'review_case','{}',%s)",
                 (job_id, org, run, job_id))
    reserved = call(conn, org, run, "reserve_run_inference", {"reservation_id": job_id, "max_model_calls": 9})
    payload = {
        "job_id": job_id, "skill_version": baseline["id"], "command_type": "review_case",
        "actor_status": "failed", "improvement_eligible": True, "mutable_skill_name": "organizer-expenses",
        "context_sha256": "d" * 64, "inference_reservation": reserved,
        "failure_observations": {"contract": "finance-failure-observation-v1", "actor_status": "failed",
                                 "financial_output_valid": False, "reason": "invalid_finance_decision_schema",
                                 "schema_error": "blocker_refs"},
        "runtime_context_artifact": {"artifact_path": f"{org}/{run}/artifacts/" + "d" * 64 + "/context.json", "content_sha256": "d" * 64},
        "diagnostic_artifact": {"artifact_path": f"{org}/{run}/artifacts/" + "e" * 64 + "/diagnostic.json", "content_sha256": "e" * 64},
    }
    return args, payload


def record_failure(conn, org, run, args, payload):
    trace = call(conn, org, run, "record_trace", {"event_type": "actor_failed", "payload": payload,
                                                "idempotency_key": "failure-" + uuid4().hex})
    return {**args, "trace_id": trace["id"]}


def test_failed_actor_uses_existing_attempt_limits_and_never_promotes_itself(state):
    conn, org, run, _ = state
    args, payload = failed_attempt(conn, org, run)
    args = record_failure(conn, org, run, args, payload)
    assert call(conn, org, run, "claim_improvement_attempt", args)["claimed"]
    assert call(conn, org, run, "claim_improvement_attempt", {**args, "attempt_id": str(uuid4())})["reason"] == "improvement_attempt_already_claimed"
    case = call(conn, org, run, "record_case", {"title": "Failed review fixture", "status": "open",
                                               "data": {"source_ids": []}, "idempotency_key": "failed-review-case"})
    case = call(conn, org, run, "get_case", {"case_id": case["id"]})
    with pytest.raises(psycopg.errors.CheckViolation, match="actual scoped actor trace"):
        conn.execute("select record_finance_case_review(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                     (org, run, case["id"], case["version"], [], args["trace_id"], payload["job_id"],
                      Jsonb({}), "case-review:" + payload["job_id"]))
    # Additional failed traces still share the run's existing three-attempt cap.
    for _ in range(2):
        next_args = record_failure(conn, org, run, {**args, "attempt_id": str(uuid4())}, payload)
        assert call(conn, org, run, "claim_improvement_attempt", next_args)["claimed"]
    excess = record_failure(conn, org, run, {**args, "attempt_id": str(uuid4())}, payload)
    assert call(conn, org, run, "claim_improvement_attempt", excess)["reason"] == "run_improvement_attempt_budget_exhausted"
    conn.execute("reset role")
    limits = conn.execute("select reserved_model_calls,reserved_improvement_attempts from finance_run_execution_limits where run_id=%s", (run,)).fetchone()
    assert limits == (129, 3)  # 9 operating + three unchanged 40-call evaluation allowances.
    assert conn.execute("select count(*) from finance_improvement_holdouts where run_id=%s", (run,)).fetchone()[0] == 0
    assert conn.execute("select count(*) from action_proposals where run_id=%s", (run,)).fetchone()[0] == 0
    assert conn.execute("select count(*) from promotions where run_id=%s", (run,)).fetchone()[0] == 0


@pytest.mark.parametrize("mutation", [
    "output", "wrong_contract", "completed", "not_eligible", "wrong_skill", "wrong_job", "no_reservation",
    "wrong_context_scope", "wrong_diagnostic_scope", "missing_context_hash", "stale_baseline", "unsafe_reason",
])
def test_failed_trace_admission_requires_exact_scoped_provenance(state, mutation):
    conn, org, run, _ = state
    args, original = failed_attempt(conn, org, run)
    payload = copy.deepcopy(original)
    if mutation == "output": payload["output"] = {"decision": "pay_vendor"}
    elif mutation == "wrong_contract": payload["failure_observations"]["contract"] = "other"
    elif mutation == "completed": payload["failure_observations"]["actor_status"] = "completed"
    elif mutation == "not_eligible": payload["improvement_eligible"] = False
    elif mutation == "wrong_skill": payload["mutable_skill_name"] = "runtime-guide"
    elif mutation == "wrong_job": payload["job_id"] = str(uuid4())
    elif mutation == "no_reservation": payload["inference_reservation"]["reservation_id"] = str(uuid4())
    elif mutation == "wrong_context_scope": payload["runtime_context_artifact"]["artifact_path"] = f"{org}/{uuid4()}/artifacts/context.json"
    elif mutation == "wrong_diagnostic_scope": payload["diagnostic_artifact"]["artifact_path"] = "foreign/artifact.json"
    elif mutation == "missing_context_hash": del payload["context_sha256"]
    elif mutation == "stale_baseline": payload["skill_version"] = str(uuid4())
    elif mutation == "unsafe_reason": payload["failure_observations"]["reason"] = "PRIVATE FREE TEXT"
    args = record_failure(conn, org, run, args, payload)
    with pytest.raises(psycopg.errors.CheckViolation, match="current completed actor trace"):
        call(conn, org, run, "claim_improvement_attempt", args)
    conn.execute("reset role")
    assert conn.execute("select reserved_model_calls,reserved_improvement_attempts from finance_run_execution_limits where run_id=%s", (run,)).fetchone() == (9, 0)


@pytest.mark.parametrize("reason,calls,eligible", [
    ("opencode_structured_output_missing", 3, True),
    ("opencode_truncated_output", 3, True),
    ("opencode_incomplete_outcome", 3, True),
    ("opencode_tool_not_permitted", 3, True),
    ("opencode_provider_or_runtime_failure", 3, True),
    ("evaluation_model_call_budget_exhausted", 8, True),
    ("evaluation_model_call_budget_exhausted", 0, False),
    ("provider_http_error", 1, False),
    ("opencode_timeout", 3, True),
])
def test_opencode_runtime_observation_admission_remains_bounded(state, reason, calls, eligible):
    conn, org, run, _ = state
    args, payload = failed_attempt(conn, org, run)
    payload["failure_observations"].update(reason=reason, api_calls=calls)
    args = record_failure(conn, org, run, args, payload)
    if eligible:
        assert call(conn, org, run, "claim_improvement_attempt", args)["claimed"]
    else:
        with pytest.raises(psycopg.errors.CheckViolation):
            call(conn, org, run, "claim_improvement_attempt", args)

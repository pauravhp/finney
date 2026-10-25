"""Trusted completed-actor rejection intake fixtures; no model or provider calls."""
import copy
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.config import Settings
from app.finance.types import FinanceError
from app.finance.workflows import queue_automatic_improvement
from app.runtime.failure_intake import REJECTED_REVIEW_FEEDBACK
from app.runtime.jobs import automatic_improvement_request
from app.service import dispatch_job


def job_and_outcome():
    job = {"id": str(uuid4()), "organization_id": str(uuid4()), "run_id": str(uuid4()),
           "command_type": "review_case", "payload": {"case_id": str(uuid4())}}
    outcome = {"status": "blocked", "actor_status": "completed", "improvement_eligible": True,
               "reason": "unsupported_prepared_review_output", "triage": {"status": "completed"},
               "trace": {"id": str(uuid4())},
               "case_review": {"status": "blocked", "reason": "unsupported_prepared_review_output"}}
    return job, outcome


def test_rejected_review_request_preserves_original_and_uses_fixed_observation():
    job, outcome = job_and_outcome()
    before = copy.deepcopy(outcome)
    outcome["feedback"] = "UNTRUSTED REQUEST TO RELAX APPROVALS"
    request = automatic_improvement_request(job, outcome, suite_id="frozen-suite")
    assert request["idempotency_key"] == "improvement-review:" + outcome["trace"]["id"]
    assert request["payload"] == {"trace_id": outcome["trace"]["id"], "suite_id": "frozen-suite",
                                  "trigger": "failed_case_review", "feedback": REJECTED_REVIEW_FEEDBACK}
    assert {k: v for k, v in outcome.items() if k != "feedback"} == before
    assert "may be an interface" in request["payload"]["feedback"]
    assert "does not establish an editable skill defect" in request["payload"]["feedback"]
    assert "UNTRUSTED" not in request["payload"]["feedback"]


@pytest.mark.parametrize("reason", [
    "completed_actor_trace_mismatch", "review_skill_provenance_required", "review_case_context_mismatch",
    "review_case_version_required", "review_case_version_chain_invalid", "review_citation_outside_scope_or_version",
    "review_context_changed_requires_new_review", "review_context_or_persistence_changed",
])
def test_provenance_scope_version_and_race_rejections_do_not_route(reason):
    job, outcome = job_and_outcome()
    outcome["reason"] = outcome["case_review"]["reason"] = reason
    assert automatic_improvement_request(job, outcome, suite_id="frozen-suite") is None


@pytest.mark.parametrize("field,value", [
    ("actor_status", "failed"), ("improvement_eligible", False), ("triage", {"status": "blocked"}),
    ("trace", {}), ("case_review", {"status": "completed"}), ("status", "failed"),
    ("triage", None), ("trace", None), ("case_review", None),
])
def test_rejected_review_requires_complete_trusted_scheduler_context(field, value):
    job, outcome = job_and_outcome(); outcome[field] = value
    assert automatic_improvement_request(job, outcome, suite_id="frozen-suite") is None


def memory_db():
    db, rows = AsyncMock(), []
    db.select.side_effect = lambda *args, **kwargs: rows
    async def insert(table, row):
        assert table == "jobs"
        rows.append({"id": str(uuid4()), **copy.deepcopy(row)})
        return rows
    db.insert.side_effect = insert
    return db, rows


@pytest.mark.asyncio
async def test_rejected_review_queue_retries_reuse_source_trace_child_without_inference():
    job, outcome = job_and_outcome(); before = copy.deepcopy(outcome)
    db, rows = memory_db()
    first = await queue_automatic_improvement(db, job, outcome)
    second = await queue_automatic_improvement(db, job, outcome)
    assert first["job_id"] == second["job_id"] and db.insert.await_count == 1
    assert rows[0]["payload"]["trigger"] == "failed_case_review" and outcome == before
    assert rows[0]["idempotency_key"] == "improvement-review:" + outcome["trace"]["id"]


@pytest.mark.asyncio
async def test_service_real_persistence_contract_rejection_stays_blocked_and_schedules_once(monkeypatch):
    job, rejected = job_and_outcome(); case_id = job["payload"]["case_id"]
    # Explicit fixture records already created by the operating actor. Their
    # existence is preserved; rejection is not evidence that the run had no effects.
    records = {"reported_obligation": {"id": "fixture-obligation", "evidence_status": "reported"},
               "finding": {"kind": "actor_tool_finding"}}
    before_records = copy.deepcopy(records)
    case = {"id": case_id, "version": 1, "data": {"source_ids": []}, "status": "open"}
    output = {"decision": "A prose classification that the operating persistence rejects", "explanation": "Fixture only.",
              "evidence_source_ids": [], "clarification": None, "proposed_action": None,
              "blocking_requirements": []}
    events = [{"name": "propose_obligation_update", "arguments": {}, "result": records["reported_obligation"]},
              {"name": "record_finding", "arguments": {"case_id": case_id}, "result": records["finding"]}]
    completed = {"status": "completed", "improvement_eligible": True, "triage": {"status": "completed"},
                 "trace": rejected["trace"], "output": output, "tool_events": events}
    trace = {"event_type": "actor_completed", "payload": {"job_id": job["id"], "skill_version": "fixture-baseline",
                                                             "output": output, "tool_events": events}}
    finance = AsyncMock()
    finance.prepare_only = False
    async def call(name, args):
        if name == "get_case": return copy.deepcopy(case)
        if name == "get_trace": return copy.deepcopy(trace)
        raise AssertionError("No original actor effect may be replayed: " + name)
    finance.call.side_effect = call
    actor = AsyncMock(side_effect=lambda *a, **kw: copy.deepcopy(completed))
    monkeypatch.setattr("app.runtime.jobs.run_job", actor)
    db, rows = memory_db()
    for _ in range(2):
        result = await dispatch_job(Settings(_env_file=None), job, finance, db)
        assert result["status"] == "blocked" and result["actor_status"] == "completed"
        assert result["reason"] == "unsupported_prepared_review_output"
        assert result["case_review"]["status"] == "blocked"
        assert result["automatic_improvement"]["status"] == "queued"
        assert result["output"] == output and result["tool_events"] == events
    assert db.insert.await_count == 1 and len(rows) == 1 and records == before_records
    assert {c.args[0] for c in finance.call.await_args_list} == {"get_case", "get_trace"}


@pytest.mark.asyncio
async def test_service_provenance_failure_never_enqueues(monkeypatch):
    job, _ = job_and_outcome()
    completed = {"status": "completed", "improvement_eligible": True, "triage": {"status": "completed"},
                 "trace": {"id": str(uuid4())}, "output": {"decision": "investigate"}}
    monkeypatch.setattr("app.runtime.jobs.run_job", AsyncMock(return_value=completed))
    monkeypatch.setattr("app.finance.review_persistence.persist_actor_review",
                        AsyncMock(return_value={"status": "blocked", "reason": "completed_actor_trace_mismatch"}))
    db, rows = memory_db()
    result = await dispatch_job(Settings(_env_file=None), job, AsyncMock(), db)
    assert result["status"] == "blocked" and result["automatic_improvement"]["status"] == "not_requested"
    assert rows == []
    db.select.assert_not_awaited(); db.insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_trace_with_existing_other_review_never_gets_a_second_child():
    job, outcome = job_and_outcome()
    db, rows = memory_db()
    rows.append({"id": str(uuid4()), "payload": {"trace_id": outcome["trace"]["id"],
                 "suite_id": "existing-suite", "trigger": "completed_case_review"}})
    with pytest.raises(FinanceError, match="improvement_queue_idempotency_conflict"):
        await queue_automatic_improvement(db, job, outcome)
    db.insert.assert_not_awaited()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_zero_call_opencode_startup_timeout_queues_only_diagnostic_observation(monkeypatch):
    from test_improvement_lifecycle import LifecyclePort

    from app.runtime.jobs import run_job
    from app.runtime.opencode import OpenCodeActorError

    port = LifecyclePort()
    actor = AsyncMock(max_iterations=8)
    actor.run.side_effect = OpenCodeActorError("opencode_timeout", private_diagnostic={
        "runtime": "opencode", "api_calls": 0, "granted_max_model_calls": 8,
        "tool_events": [], "original_final_response": None,
    })
    monkeypatch.setattr("app.runtime.opencode.OpenCodeActor", lambda *a, **kw: actor)
    job = {"id": str(uuid4()), "organization_id": str(port.scope.organization_id),
           "run_id": str(port.scope.run_id), "command_type": "review_case", "payload": {}}
    outcome = await run_job(job, port, settings=Settings(_env_file=None,
        finance_actor_runtime="opencode", finance_model_api_key="fixture-only"))
    assert outcome["status"] == "blocked" and outcome["reason"] == "opencode_timeout"
    assert outcome["improvement_eligible"] is True and "output" not in outcome
    assert outcome["failure_observations"]["api_calls"] == 0
    assert outcome["failure_observations"]["tool_event_count"] == 0
    assert automatic_improvement_request(job, outcome, suite_id="frozen-suite")["payload"]["trigger"] == "failed_case_review"
    assert not any(name in {"record_case", "propose_obligation_update", "record_finding", "record_case_review",
                            "create_approval_request", "execute_payment"} for name, _ in port.calls)
    assert len(port.reservations) == 1 and not port.attempts and not port.holdouts

"""Real parser/worker control flow with declared subprocess/storage fixtures; no inference."""
import copy
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_improvement_lifecycle import LifecyclePort
from test_runtime_format import DECISION, FakeProcess

from app.config import Settings
from app.finance.workflows import queue_automatic_improvement
from app.runtime import hermes
from app.runtime.failure_intake import (
    MAX_DIAGNOSTIC_BYTES,
    eligible_failed_trace,
    failure_observations,
    private_failure_artifact,
)
from app.runtime.jobs import automatic_improvement_request, run_job


@pytest.mark.asyncio
async def test_invalid_blocker_refs_is_failed_diagnosable_and_never_a_finance_decision(monkeypatch):
    port = LifecyclePort()
    bad = copy.deepcopy(DECISION)
    bad["explanation"] = "PRIVATE MODEL OUTPUT"
    bad["blocking_requirements"][0]["supporting_refs"] = []
    process = FakeProcess([
        {"type": "result", "result": {"final_response": json.dumps(bad), "api_calls": 4,
                                      "completed": True, "failed": False, "partial": False},
         "usage": {"input_tokens": 200}, "provider_request_ids": ["PRIVATE PROVIDER ID"]},
    ])
    monkeypatch.setattr(hermes, "verify_source", lambda source: None)
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(hermes.asyncio, "create_subprocess_exec", spawn)
    job = {"id": str(uuid4()), "organization_id": str(port.scope.organization_id),
           "run_id": str(port.scope.run_id), "command_type": "review_case", "payload": {}}
    outcome = await run_job(job, port, settings=Settings(_env_file=None, finance_model_api_key="fixture"))
    assert outcome["status"] == "blocked"
    assert outcome["reason"] == "invalid_finance_decision_schema"
    assert outcome["improvement_eligible"] is True
    assert "output" not in outcome and "trace" not in outcome
    assert outcome["failure_observations"]["schema_error"] == "blocker_refs"
    assert outcome["failure_observations"]["api_calls"] == 4
    failed = next(t for t in port.traces.values() if t["event_type"] == "actor_failed")
    assert eligible_failed_trace(failed["payload"])
    assert all(t["event_type"] != "actor_completed" for t in port.traces.values())
    assert "PRIVATE" not in json.dumps(outcome) and "PRIVATE" not in json.dumps(failed)
    assert "PRIVATE MODEL OUTPUT" in port.artifacts[failed["payload"]["diagnostic_artifact"]["artifact_path"]]
    assert spawn.await_count == 1
    assert len(port.reservations) == 1 and not port.attempts and not port.holdouts
    assert not any(name in {"create_approval_request", "record_case_review", "confirm_payment"}
                   for name, _ in port.calls)
    assert len([c for c in port.calls if c[0] == "reserve_run_inference"]) == 1
    # Scheduler dedupe remains exactly the same source-trace key; it creates no budget itself.
    rows = []
    db = AsyncMock()
    db.select.side_effect = lambda *a, **kw: rows
    async def insert(table, args):
        rows.append({"id": str(uuid4()), **args})
        return rows
    db.insert.side_effect = insert
    first = await queue_automatic_improvement(db, job, outcome)
    second = await queue_automatic_improvement(db, job, outcome)
    assert first["job_id"] == second["job_id"] and db.insert.await_count == 1
    assert rows[0]["payload"]["trigger"] == "failed_case_review"

    # The real evaluator receives only the projection, claims the unchanged
    # durable allowance and freezes pairs before reviewer diagnosis.
    reviewer = AsyncMock()
    reviewer.complete.return_value = {"output": {"issue_type": "no_defect"}}
    jev = AsyncMock()
    jev.evaluate_trace.return_value = {"scores": {}}
    monkeypatch.setattr("app.models.GenerativeModel", lambda config: reviewer)
    monkeypatch.setattr("app.runtime.jobs.JevClient", lambda key: jev)
    follow_up = {**rows[0], "id": first["job_id"]}
    reviewed = await run_job(follow_up, port, settings=Settings(
        _env_file=None, finance_model_api_key="fixture", ai_gateway_api_key="fixture"))
    assert reviewed["status"] == "completed"
    assert reviewed["improvement"]["status"] == "rejected"
    assert reviewed["improvement"]["reason"] == "no_source_supported_procedure_defect"
    assert reviewed["improvement"]["model_call_budget"]["used_upper_bound"] == 2
    context = json.loads(reviewer.complete.await_args.args[1])
    assert context["trace"]["failure_observations"]["schema_error"] == "blocker_refs"
    assert "PRIVATE" not in json.dumps(context)
    assert "output" not in context["trace"]
    assert len(port.attempts) == 1 and not port.holdouts and not port.promotions
    assert spawn.await_count == 1


def test_failure_projection_excludes_arbitrary_exception_text_and_tool_bodies():
    diagnostic = {"original_final_response": "PRIVATE", "api_calls": True,
                  "tool_events": [{"name": "PRIVATE", "arguments": {"key": "PRIVATE"},
                                   "result": "PRIVATE"}] * 100}
    observation = failure_observations("UNTRUSTED TEXT", diagnostic)
    assert "PRIVATE" not in json.dumps(observation) and "UNTRUSTED TEXT" not in json.dumps(observation)
    assert observation["tool_event_count"] == 100 and observation["tool_events_truncated"]
    assert "api_calls" not in observation
    raw = private_failure_artifact({"private": '"\\' * MAX_DIAGNOSTIC_BYTES})
    assert len(raw.encode()) <= MAX_DIAGNOSTIC_BYTES and json.loads(raw)["truncated"]


@pytest.mark.parametrize("status,eligible,trace", [
    ("completed", True, {"id": "fixture"}), ("blocked", False, {"id": "fixture"}),
    ("blocked", True, {}),
])
def test_failure_scheduler_does_not_infer_success_or_missing_provenance(status, eligible, trace):
    outcome = {"status": status, "improvement_eligible": eligible, "failure_trace": trace,
               "failure_observations": {"contract": "finance-failure-observation-v1"}}
    assert automatic_improvement_request({"command_type": "review_case"}, outcome, suite_id="fixture") is None


@pytest.mark.asyncio
async def test_persistence_failure_keeps_primary_failure_and_disables_learning(monkeypatch):
    port = LifecyclePort()
    original = port.call
    async def fail_artifact(name, args):
        if name == "put_artifact" and args.get("name") == "actor-failed-diagnostic.json":
            raise RuntimeError("PRIVATE STORAGE DETAIL")
        return await original(name, args)
    port.call = fail_artifact
    actor = AsyncMock(max_iterations=8)
    actor.run.side_effect = hermes.HermesActorError("hermes_timeout", private_diagnostic={"tool_events": []})
    monkeypatch.setattr("app.runtime.jobs.HermesActor", lambda *a, **kw: actor)
    job = {"id": str(uuid4()), "organization_id": str(port.scope.organization_id),
           "run_id": str(port.scope.run_id), "command_type": "review_case", "payload": {}}
    outcome = await run_job(job, port, settings=Settings(_env_file=None, finance_model_api_key="fixture"))
    assert outcome["status"] == "blocked" and outcome["reason"] == "hermes_timeout"
    assert outcome["improvement_eligible"] is False
    assert outcome["failure_trace"]["error_type"] == "RuntimeError"
    assert "PRIVATE" not in json.dumps(outcome)
    assert automatic_improvement_request(job, outcome, suite_id="fixture") is None


@pytest.mark.asyncio
async def test_dispatch_queues_failed_diagnosis_without_persisting_financial_review(monkeypatch):
    from app.service import dispatch_job

    outcome = {"status": "blocked", "reason": "invalid_finance_decision_schema",
               "improvement_eligible": True, "failure_trace": {"id": "fixture-failed"},
               "failure_observations": {"contract": "finance-failure-observation-v1"}}
    job = {"id": str(uuid4()), "organization_id": str(uuid4()), "run_id": str(uuid4()),
           "command_type": "review_case", "payload": {}}
    actor = AsyncMock(return_value=copy.deepcopy(outcome))
    queued = AsyncMock(return_value={"status": "queued", "job_id": "fixture-review"})
    persisted = AsyncMock()
    monkeypatch.setattr("app.runtime.jobs.run_job", actor)
    monkeypatch.setattr("app.finance.workflows.queue_automatic_improvement", queued)
    monkeypatch.setattr("app.finance.review_persistence.persist_actor_review", persisted)
    result = await dispatch_job(Settings(_env_file=None), job, AsyncMock(), AsyncMock())
    assert result["status"] == "blocked" and result["automatic_improvement"]["status"] == "queued"
    queued.assert_awaited_once()
    persisted.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", [
    "opencode_structured_output_missing", "opencode_truncated_output", "opencode_incomplete_outcome",
    "opencode_tool_not_permitted", "opencode_provider_or_runtime_failure", "evaluation_model_call_budget_exhausted",
    "opencode_timeout", "opencode_transport_error", "opencode_protocol_error", "provider_http_error",
])
async def test_opencode_learning_reason_allowlist_excludes_auth_and_infrastructure(monkeypatch, reason):
    from app.runtime.failure_intake import ELIGIBLE_FAILURES

    port = LifecyclePort()
    actor = AsyncMock(max_iterations=8)
    actor.run.side_effect = hermes.HermesActorError(reason, private_diagnostic={
        "runtime": "opencode", "tool_events": [], "api_calls": 3, "granted_max_model_calls": 8,
    })
    monkeypatch.setattr("app.runtime.jobs.HermesActor", lambda *a, **kw: actor)
    job = {"id": str(uuid4()), "organization_id": str(port.scope.organization_id),
           "run_id": str(port.scope.run_id), "command_type": "review_case", "payload": {}}
    outcome = await run_job(job, port, settings=Settings(_env_file=None, finance_model_api_key="fixture"))
    assert outcome["status"] == "blocked" and "output" not in outcome
    assert outcome["improvement_eligible"] is (reason in ELIGIBLE_FAILURES)
    assert bool(automatic_improvement_request(job, outcome, suite_id="fixture")) is (reason in ELIGIBLE_FAILURES)

"""Local protocol tests; scripted completions are not measured model evidence."""
import copy
import hashlib
import json
from dataclasses import replace
from uuid import uuid4

import pytest
from test_improvement_lifecycle import LifecyclePort

from app.improvement.dataset import FinanceDataset
from app.improvement.runtime_preflight import (
    PREFLIGHT_CASES,
    learning_actor,
    require_runtime_preflight,
    run_runtime_preflight,
    runtime_binding,
)
from app.models import ModelConfig, ModelError
from app.runtime.jobs import DEFAULT_SKILL
from app.runtime.opencode import PIN, OpenCodeActorError

CONFIG = ModelConfig("claude-sonnet-5-5", "https://fixture.invalid", "SECRET_SENTINEL",
                     api_mode="anthropic_messages")
BASELINE = DEFAULT_SKILL.read_text()
CONTEXT = {"prefix": "Frozen runtime prefix\n", "suffix": "\nFrozen runtime suffix",
           "active_skill_sha256": hashlib.sha256(BASELINE.encode()).hexdigest()}


def actor_fixture(*, fail=False, wrong_model=False):
    actor = learning_actor(CONFIG)
    actor.calls = []

    async def run(prompt, skill, scoped, **kwargs):
        actor.calls.append(copy.deepcopy((prompt, skill, kwargs)))
        assert scoped.prepare_only and kwargs["max_model_calls"] == 8
        assert "record_finding" not in kwargs["allowed_tools"]
        assert "required_source_refs" not in json.dumps(prompt)
        if fail:
            raise OpenCodeActorError("opencode_provider_or_runtime_failure", private_diagnostic={
                "original_final_response": "PRIVATE_DIAGNOSTIC_SENTINEL", "api_calls": 2,
                "provider_calls": [{"finish_reason": "max_tokens", "max_tokens": 8192}],
            })
        return {"output": {"decision": "fixture_no_action", "explanation": "Fixture, not real inference.",
                           "evidence_source_ids": [], "clarification": None,
                           "proposed_action": {"action": "no_action"}, "blocking_requirements": []},
                "tool_events": [], "evidence": {"model": "claude-sonnet-4-6" if wrong_model else CONFIG.model,
                                                 "runtime": "opencode", "revision": PIN["revision"],
                                                 "api_calls": 1, "usage": {"fixture": True}}}
    actor.run = run
    return actor


async def execute(actor, port, study=None):
    return await run_runtime_preflight(actor=actor, tools=port, study_id=study or str(uuid4()),
                                       baseline_content=BASELINE, fixed_context=CONTEXT)


@pytest.mark.asyncio
async def test_completed_but_financially_wrong_baseline_is_valid_testing_ground(monkeypatch):
    # Observe public packet access without opening the new promotion dataset.
    opened = []
    original = FinanceDataset.public_packet
    def packet(self, case_id):
        opened.append(case_id)
        assert case_id in PREFLIGHT_CASES
        return original(self, case_id)
    monkeypatch.setattr(FinanceDataset, "public_packet", packet)
    actor, port = actor_fixture(), LifecyclePort()
    result = await execute(actor, port)
    assert result["status"] == "runtime_ready" and len(actor.calls) == 2
    assert all(row["runtime_valid"] and not row["financial_correct"] for row in result["rows"])
    assert set(opened) == set(PREFLIGHT_CASES)
    assert result["max_reserved_calls"] == 16 and result["api_calls_observed"] == 2
    assert not result["final_holdout_opened"] and not port.holdouts and not port.promotions
    assert "SECRET_SENTINEL" not in json.dumps(port.artifacts)
    assert "ground_truth" not in json.dumps(actor.calls, default=list)
    loaded = await require_runtime_preflight(tools=port, receipt=result["summary_artifact"],
                                             actor=actor, baseline_content=BASELINE, fixed_context=CONTEXT)
    assert loaded["binding"]["max_tokens"] == 8192
    assert loaded["binding"]["request_policy"]["thinking"] == {"type": "between_tools"}
    assert loaded["binding"]["request_policy"]["output_config"] == {"effort": "high"}
    assert {name for name, _ in port.calls} <= {"put_artifact", "read_artifact", "reserve_run_inference"}


@pytest.mark.asyncio
async def test_runtime_failure_has_no_financial_verdict_no_retry_and_retains_private_diagnostics():
    actor, port = actor_fixture(fail=True), LifecyclePort()
    result = await execute(actor, port)
    assert result["status"] == "blocked" and len(actor.calls) == 1
    row = result["rows"][0]
    assert row["runtime_valid"] is False and row["financial_correct"] is None
    assert row["diagnostic_status"] == "persisted"
    assert "PRIVATE_DIAGNOSTIC_SENTINEL" in port.artifacts[row["diagnostic_artifact"]["artifact_path"]]
    assert "PRIVATE_DIAGNOSTIC_SENTINEL" not in json.dumps(result)
    assert result["max_reserved_calls"] == 16
    with pytest.raises(ModelError, match="not_ready_or_drifted"):
        await require_runtime_preflight(tools=port, receipt=result["summary_artifact"],
                                        actor=actor, baseline_content=BASELINE, fixed_context=CONTEXT)


@pytest.mark.asyncio
async def test_reusing_study_identity_cannot_replay_completed_or_failed_inference():
    actor, port, study = actor_fixture(fail=True), LifecyclePort(), str(uuid4())
    await execute(actor, port, study)
    with pytest.raises(ModelError, match="reservation_denied"):
        await execute(actor, port, study)
    assert len(actor.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["skill", "context", "model", "tokens", "provider_timeout", "actor_timeout"])
async def test_preflight_cannot_authorize_different_study_configuration(drift):
    actor, port = actor_fixture(), LifecyclePort()
    result = await execute(actor, port)
    baseline, context = BASELINE, CONTEXT
    if drift == "skill":
        baseline += "changed"
    elif drift == "context":
        context = {**CONTEXT, "prefix": "changed"}
    elif drift == "model":
        actor.config = replace(actor.config, model="claude-sonnet-4-6")
    elif drift == "tokens":
        actor.config = replace(actor.config, max_tokens=1600)
    elif drift == "provider_timeout":
        actor.config = replace(actor.config, timeout_seconds=45)
    else:
        actor.timeout_seconds = 120
    with pytest.raises(ModelError, match="preflight_"):
        await require_runtime_preflight(tools=port, receipt=result["summary_artifact"],
                                        actor=actor, baseline_content=baseline, fixed_context=context)


@pytest.mark.asyncio
async def test_wrong_actual_model_is_blocked_and_diagnostic_persistence_failure_is_explicit():
    actor, port = actor_fixture(wrong_model=True), LifecyclePort()
    result = await execute(actor, port)
    assert result["status"] == "blocked" and len(actor.calls) == 1
    assert result["rows"][0]["reason"] == "learning_preflight_evidence_invalid"
    class UnavailablePort(LifecyclePort):
        async def call(self, name, args):
            if name == "put_artifact" and args["name"].endswith("-failure.json"):
                raise ValueError("PRIVATE_UPLOAD_ERROR")
            return await super().call(name, args)
    result = await execute(actor_fixture(fail=True), UnavailablePort())
    assert result["rows"][0]["diagnostic_status"] == "unavailable"
    assert "PRIVATE_UPLOAD_ERROR" not in json.dumps(result)


def test_model_boundary_and_context_required_before_any_inference():
    with pytest.raises(ModelError, match="model_mismatch"):
        learning_actor(replace(CONFIG, model="claude-sonnet-4-6"))
    with pytest.raises(ModelError, match="context_required"):
        runtime_binding(learning_actor(CONFIG), baseline_content=BASELINE, fixed_context={})


@pytest.mark.asyncio
async def test_online_sonnet55_learning_requires_scoped_preflight_before_suite_or_search(monkeypatch):
    from app.config import Settings
    from app.improvement.blockers import BLOCKER_SUITE_ID
    from app.runtime.jobs import ensure_baseline, run_job
    from app.runtime.operation_policy import runtime_operation_policy
    from app.runtime.skills import runtime_skill_context

    port = LifecyclePort()
    baseline = await ensure_baseline(port)
    context, routing, fixed = runtime_skill_context(
        "review_case", {}, {"title": "organizer reimbursement"},
        active_skill=baseline, active_content=BASELINE,
    )
    context_receipt = await port.call("put_artifact", {"name": "fixture-context.json", "content": json.dumps({
        "fixed_context": fixed, "immutable_policy": runtime_operation_policy(),
    })})
    trace = await port.call("record_trace", {"event_type": "actor_completed", "payload": {
        **routing, "skill_version": baseline["id"], "runtime_context_artifact": context_receipt,
        "context_sha256": hashlib.sha256(context.encode()).hexdigest(), "model_identity": CONFIG.model,
        "output": {"decision": "fixture"}, "tool_events": [],
    }})
    job = {"id": str(uuid4()), "organization_id": str(port.scope.organization_id),
           "run_id": str(port.scope.run_id), "command_type": "evaluate_improvement",
           "payload": {"trace_id": trace["id"], "suite_id": BLOCKER_SUITE_ID}}
    settings = Settings(_env_file=None, finance_actor_runtime="opencode", finance_improvement_method="harness2",
                        finance_model=CONFIG.model, finance_model_base_url=CONFIG.base_url,
                        finance_model_api_key="fixture", ai_gateway_api_key="fixture")
    suites = []
    def suite(*args):
        suites.append(args)
        return object()
    monkeypatch.setattr("app.improvement.suites.organizer_expense_suite", suite)
    blocked = await run_job(job, port, settings=settings)
    assert blocked["reason"] == "learning_runtime_preflight_missing"
    assert not suites and not port.attempts and not port.holdouts and not port.reservations

    preflight = await run_runtime_preflight(actor=actor_fixture(), tools=port, study_id=str(uuid4()),
                                            baseline_content=BASELINE, fixed_context=fixed)
    configs = []
    def search(actor, editor):
        configs.append((actor.config, editor.config, actor.max_iterations, actor.timeout_seconds))
        return object()
    class Engine:
        def __init__(self, actor, reviewer, jev, **kwargs):
            assert reviewer.config == actor.config
        async def run(self, **kwargs):
            assert kwargs["max_model_calls"] == 96
            return {"status": "rejected", "reason": "fixture_no_real_evaluation"}
    monkeypatch.setattr("app.improvement.harness2_candidate.make_harness2_candidate_search", search)
    monkeypatch.setattr("app.improvement.engine.ImprovementEngine", Engine)
    settings = settings.model_copy(update={
        "finance_learning_preflight_artifact": preflight["summary_artifact"]["artifact_path"],
        "finance_learning_preflight_sha256": preflight["summary_artifact"]["content_sha256"],
    })
    passed = await run_job(job, port, settings=settings)
    assert passed["status"] == "completed" and len(suites) == 1 and len(configs) == 1
    actor_config, editor_config, iterations, timeout = configs[0]
    assert actor_config == editor_config and actor_config.max_tokens == 8192
    assert iterations == 8 and timeout == 240
    # A different event cannot reuse the owner's receipt.
    other = LifecyclePort()
    other.scope = type(port.scope)(port.scope.organization_id, uuid4())
    other.artifacts = port.artifacts
    with pytest.raises(ModelError, match="not_ready_or_drifted"):
        await require_runtime_preflight(tools=other, receipt=preflight["summary_artifact"],
                                        actor=actor_fixture(), baseline_content=BASELINE, fixed_context=fixed)

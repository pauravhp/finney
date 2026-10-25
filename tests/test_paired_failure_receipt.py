"""Future paired failure evidence; fixtures never count as successful evaluation."""
import json

import pytest
from test_improvement_lifecycle import (
    LifecycleActor,
    LifecycleJev,
    LifecyclePort,
    LifecycleReviewer,
)

from app.improvement.blockers import BLOCKER_SUITE_ID
from app.improvement.engine import ImprovementEngine
from app.improvement.suites import organizer_expense_suite
from app.models import ModelError
from app.runtime.jobs import DEFAULT_SKILL, ensure_baseline
from app.runtime.opencode import OpenCodeActorError


async def attempt(*, unavailable=False, oversized=False, no_diagnostic=False):
    class Port(LifecyclePort):
        async def call(self, name, args):
            if unavailable and name == "put_artifact" and args.get("name", "").startswith("paired-failure-"):
                raise ValueError("PRIVATE_PERSISTENCE_BODY_SENTINEL")
            return await super().call(name, args)
    port = Port()
    baseline = await ensure_baseline(port)
    suite = organizer_expense_suite(port, BLOCKER_SUITE_ID)
    class Actor(LifecycleActor):
        attempts = 0
        async def run(self, prompt, skill, tools, **kwargs):
            self.attempts += 1
            if self.attempts == 2:
                if no_diagnostic:
                    raise ModelError("opencode_provider_or_runtime_failure")
                raise OpenCodeActorError("opencode_provider_or_runtime_failure", private_diagnostic={
                    "original_final_response": "PRIVATE_PAIRED_FAILURE_SENTINEL" + ("x" * 600_000 if oversized else ""),
                    "tool_events": [], "api_calls": 2,
                })
            return await super().run(prompt, skill, tools, **kwargs)
    actor = Actor(suite)
    result = await ImprovementEngine(actor, LifecycleReviewer(port), LifecycleJev()).run(
        trace={"id": "fixture-observed", "output": {"explanation": "Fixture repeated reads."}},
        baseline=baseline, baseline_content=DEFAULT_SKILL.read_text(), suite=suite, tools=port,
    )
    return result, port, actor, baseline


@pytest.mark.asyncio
@pytest.mark.parametrize("oversized", [False, True])
async def test_failed_candidate_keeps_private_bounded_evidence_and_aborts_without_scores_or_transfer(oversized):
    result, port, actor, baseline = await attempt(oversized=oversized)
    assert result["status"] == "blocked" and result["reason"] == "opencode_provider_or_runtime_failure"
    assert actor.attempts == 2 and len(result["rows"]) == 1
    assert result["rows"][0]["variant"] == "baseline"
    failure = result["paired_actor_failure"]
    assert failure["variant"] == "candidate" and failure["group"] == "validation"
    assert failure["case_key"] == result["rows"][0]["case_key"]
    assert failure["phase"] == "paired_actor_execution" and failure["diagnostic_status"] == "persisted"
    private = port.artifacts[failure["diagnostic_artifact"]["artifact_path"]]
    assert len(private.encode()) <= 512_000
    assert "PRIVATE_PAIRED_FAILURE_SENTINEL" in private
    assert json.loads(private).get("truncated", False) == oversized
    assert "PRIVATE_PAIRED_FAILURE_SENTINEL" not in json.dumps(result)
    assert "PRIVATE_PAIRED_FAILURE_SENTINEL" not in json.dumps(port.traces)
    evaluation = next(iter(port.evaluations.values()))
    assert evaluation["status"] == "blocked" and evaluation["metrics"]["paired_actor_failure"] == failure
    assert not evaluation["metrics"]["gate_passed"] and evaluation["metrics"]["completed_rows"] == 1
    assert port.holdouts == set() and port.active == baseline["id"] and not port.promotions
    # Failed invocation stays conservatively charged, no reservation refund.
    assert result["model_call_budget"]["used_upper_bound"] >= 3 + actor.max_iterations


@pytest.mark.asyncio
async def test_diagnostic_upload_failure_does_not_replace_primary_failure_or_leak_exception_body():
    result, port, actor, baseline = await attempt(unavailable=True)
    assert result["reason"] == "opencode_provider_or_runtime_failure" and result["status"] == "blocked"
    assert result["paired_actor_failure"]["diagnostic_status"] == "unavailable"
    assert result["paired_actor_failure"]["diagnostic_error_type"] == "ValueError"
    assert "PRIVATE_PERSISTENCE_BODY_SENTINEL" not in json.dumps(result)
    assert actor.attempts == 2 and not port.holdouts and port.active == baseline["id"]


@pytest.mark.asyncio
async def test_missing_diagnostic_is_explicit_not_fabricated():
    result, port, actor, _baseline = await attempt(no_diagnostic=True)
    assert result["paired_actor_failure"]["diagnostic_status"] == "not_supplied"
    assert "diagnostic_artifact" not in result["paired_actor_failure"]
    assert actor.attempts == 2 and not port.holdouts

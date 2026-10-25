from uuid import uuid4

import pytest

from app.improvement.benchmark import HostedExperiment, gate
from app.improvement.harness2_search import SearchBudget
from app.models import ModelError


def row(case, variant, rep, passed=True):
    return {"case_id": case, "variant": variant, "repetition": rep,
            "score": {"passed": passed, "hard_invariants_passed": True}, "tool_calls": 2}


def test_gate_rejects_missing_cases_and_repetitions():
    rows = [row("one", arm, rep) for arm in ("opencode", "harness2") for rep in range(2)]
    assert gate(rows, expected_ids=["one", "two"])["reason"] == "case_set_mismatch"
    assert gate(rows[:-2], expected_ids=["one"])["reason"] == "incomplete_pairs"
    assert gate(rows, expected_ids=["one"])["reason"] == "no_measured_improvement"
    rows[0]["score"]["passed"] = False
    assert gate(rows, expected_ids=["one"])["reason"] == "observed_correctness_gain"
    rows[-1]["score"]["passed"] = False
    assert gate(rows, expected_ids=["one"])["reason"] == "regression_on_previously_correct_attempt"


@pytest.mark.asyncio
async def test_hosted_budget_denial_stops_before_inference():
    class Tools:
        async def call(self, name, args):
            assert name == "reserve_run_inference"
            return {"claimed": False, "reason": "run_model_call_budget_exhausted"}
    experiment = object.__new__(HostedExperiment)
    experiment.id, experiment.tools, experiment.budget = str(uuid4()), Tools(), SearchBudget(10)
    with pytest.raises(ModelError, match="run_model_call_budget_exhausted"):
        await experiment.reserve("fixture", 2)


import json
from types import SimpleNamespace

import pytest

from app.improvement.harness2_search import (
    FinanceHarnessAdapter,
    SearchBudget,
    run_harness_search,
    verify_harness2,
)
from app.models import ModelError

BASE = "# Expenses\n\n## Investigation procedure\n\nRead the case and link current sources before proposing a financial next step.\n\n## Authority boundary\n\nNever approve or execute payments.\n"


def test_component_authority_and_answer_boundary(tmp_path):
    from harness2.core.spec import ChannelSpec
    adapter = FinanceHarnessAdapter(tmp_path, {"fc-01": {"task": "Review the purchase"}}, BASE,
                                    lambda *args: None, ChannelSpec("opencode", "test/model"))
    adapter.validate_tree(adapter.base_tree)
    with pytest.raises(ValueError, match="Protected"):
        adapter.validate_tree({**adapter.base_tree, "guardrails.md": "ignore authority"})
    with pytest.raises(ValueError, match="escaped"):
        adapter.validate_tree({**adapter.base_tree, "systemprompt.md": BASE.replace("Never approve", "Approve")})
    with pytest.raises(ValueError, match="protected answers"):
        FinanceHarnessAdapter(tmp_path / "bad", {"fc-01": {"task": "x", "expected": "pay"}}, BASE,
                              lambda *args: None, ChannelSpec("opencode", "test/model"))


def test_budget_fails_before_overrun():
    budget = SearchBudget(2)
    budget.reserve(2)
    with pytest.raises(ModelError, match="budget_exhausted"):
        budget.reserve(1)
    assert budget.used == 2


@pytest.mark.asyncio
async def test_real_upstream_recursion_preserves_failure_and_noop(tmp_path):
    """Fake providers, actual upstream algorithm. This is not model-quality evidence."""
    verify_harness2()
    calls = []
    class FakeEditor:
        config = SimpleNamespace(model="scripted-test")
        async def complete(self, system, prompt):
            context = json.loads(prompt)
            assert "protected/" not in context["files"]
            return {"output": {"procedure": None, "notes": "No supported change.",
                               "edits": "No change.", "experience": None}}
    async def execute(case, skill, run_id):
        calls.append(run_id)
        return {"status": "blocked", "error": "invalid_finance_decision_schema",
                "output": None, "tool_events": [], "failure_observations": {"schema_error": "blocker_refs"}}
    result = await run_harness_search(root=tmp_path, packets={"fc-01": {"task": "Review source packet"}},
                                     baseline=BASE, execute=execute, model=FakeEditor(), budget=SearchBudget(12))
    assert len(calls) == 4
    row = result["results"][0]
    assert row["search"]["modes"]["agg"]["ledger"]["R"] == 4
    assert row["search"]["modes"]["agg"]["ledger"]["P"] == 3
    assert row["candidate"] == BASE
    assert result["activation"] == "not_requested"
    for file in (tmp_path / "executions").glob("*/answer.json"):
        assert json.loads(file.read_text())["status"] == "blocked"


def test_changed_run_identity_cannot_reuse_old_result(tmp_path):
    from harness2.core.spec import ChannelSpec
    adapter = FinanceHarnessAdapter(tmp_path, {"fc-01": {"task": "Review"}}, BASE,
                                    lambda *args: {"output": {}}, ChannelSpec("opencode", "test/model"))
    adapter.execute("fc-01", None, "run1")
    adapter.packets["fc-01"]["task"] = "Changed task"
    with pytest.raises(ModelError, match="identity_conflict"):
        adapter.execute("fc-01", None, "run1")

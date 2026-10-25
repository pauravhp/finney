"""Full workflow fixtures: real Harness2/scorer, scripted providers, no quality claims."""
import copy
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.finance.tools import FinanceToolClient
from app.finance.types import Scope
from app.improvement.benchmark import HostedExperiment
from app.improvement.dataset import FinanceDataset

pytest.importorskip("harness2", reason="install the learning extra for upstream integration tests")

SECRET = "fixture-secret-never-export"
PROCEDURE = (
    "Inspect current source versions, actual payer and remaining liability before "
    "preparing a supported action. Preserve stage-specific authority and uncertainty. "
    "FIXTURE INVESTIGATION: this text exercises orchestration, not model learning."
)


class RecordingBackend:
    """Only trusted evaluation bookkeeping may leave a captured snapshot."""
    def __init__(self, *, heldout_claimed=True, reserve_claimed=True):
        self.calls, self.artifacts = [], []
        self.evaluations = {}
        self.heldout_claimed, self.reserve_claimed = heldout_claimed, reserve_claimed
        self.reserve_count = 0
        self.deny_reservations_from = None

    async def rpc(self, name, args):
        self.calls.append((name, copy.deepcopy(args)))
        if name == "claim_finance_learning_holdout":
            return {"claimed": self.heldout_claimed}
        assert name == "finance_kernel_call", (name, args)
        operation = args["p_operation"]
        if operation == "reserve_run_inference":
            self.reserve_count += 1
            denied = self.deny_reservations_from is not None and self.reserve_count >= self.deny_reservations_from
            return {"claimed": self.reserve_claimed and not denied, "reason": "fixture_denied"}
        if operation == "get_active_skill":
            return None
        if operation == "save_skill_version":
            return {"id": str(uuid4())}
        if operation == "record_eval_run":
            # Match the actual kernel upsert: existing version linkage is immutable.
            body = args["p_arguments"]
            existing = self.evaluations.get(body["id"])
            if existing is None:
                self.evaluations[body["id"]] = copy.deepcopy(body)
            else:
                for key in ("status", "metrics", "artifact_path"):
                    existing[key] = copy.deepcopy(body.get(key))
            return copy.deepcopy(self.evaluations[body["id"]])
        assert operation in {"record_eval_result", "record_trace"}, operation
        return {"ok": True}

    async def upload(self, bucket, path, content, content_type):
        assert bucket == "finance-artifacts"
        self.artifacts.append((path, content.decode()))


def oracle_output(dataset, case_id):
    """Evaluator-shaped fixture input; never supplied to editor context."""
    key = dataset.expected(case_id)
    action = {"action": key["action"]}
    if key["amount_minor"] is not None:
        action.update(amount_minor=key["amount_minor"], currency=key["currency"],
                      evidence_refs=key["required_source_refs"], recipient_name=key["recipient_name"])
    output = {
        "decision": "scripted_fixture_decision",
        "explanation": "Unit-test oracle input, not a real model result.",
        "evidence_source_ids": [ref["id"] for ref in key["required_source_refs"]],
        "clarification": "Please verify the missing or conflicting source fact." if key["clarification_required"] else None,
        "proposed_action": action,
        "blocking_requirements": [
            {"stage": stage, "requirement": requirement, "supporting_refs": [
                {"kind": "policy", "id": "fc-policy-1", "version": 1}]}
            for stage, requirement in key["required_blockers"]
        ],
    }
    if key["report_checks"]:
        output["finance_report"] = key["report_checks"]
    return output


def fixture_experiment(monkeypatch, tmp_path, *, heldout_claimed=True, changed=True):
    dataset = FinanceDataset(evaluator=True)
    evaluator = FinanceDataset(evaluator=True, allow_heldout=True)
    title_ids = {evaluator.public_packet(cid)["title"]: cid for cid in evaluator.case_ids()}
    actor_calls, editor_contexts = [], []
    backend = RecordingBackend(heldout_claimed=heldout_claimed)
    tools = FinanceToolClient(Scope(uuid4(), uuid4()), backend)

    class Actor:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, prompt, skill, scoped, **kwargs):
            snapshot = prompt["case"]
            case_id = title_ids[snapshot["cases"][0]["title"]]
            actor_calls.append((case_id, "FIXTURE INVESTIGATION" in skill))
            assert prompt["mode"] == "prepare_only"
            assert scoped.prepare_only
            assert "record_finding" not in kwargs["allowed_tools"]
            serialized = json.dumps(prompt)
            assert SECRET not in serialized
            assert '"report_checks"' not in serialized
            assert '"required_source_refs"' not in serialized
            output = oracle_output(evaluator, case_id)
            candidate = "FIXTURE INVESTIGATION" in skill
            if not candidate:
                # Deliberate fixture failure exercises the path, not empirical gain.
                output["proposed_action"] = {"action": "investigate"}
                output["evidence_source_ids"] = []
            return {"output": output, "tool_events": [],
                    "evidence": {"api_calls": 1, "usage": {"fixture": True}}}

    class Editor:
        def __init__(self, config, **kwargs):
            self.config = config

        async def complete(self, system, prompt):
            editor_contexts.append(prompt)
            for forbidden in (SECRET, "ground_truth.json", '"report_checks"', '"required_source_refs"'):
                assert forbidden not in prompt
            return {"output": {"procedure": PROCEDURE if changed else None,
                               "notes": "Scripted fixture edit.", "edits": "Fixture contrast only.",
                               "experience": ({"cue": "A source-linked financial request.",
                                               "lesson": "Read current documents before proposing action.",
                                               "evidence": "Scripted execution output changed after procedure edit.",
                                               "confidence": "Fixture only; no generalization claim."} if changed else None)},
                    "usage": {"fixture": True}}

    monkeypatch.setattr("app.improvement.benchmark.HermesActor", Actor)
    monkeypatch.setattr("app.runtime.opencode.OpenCodeActor", Actor)
    monkeypatch.setattr("app.improvement.benchmark.OpenCodeEditor", Editor)
    settings = SimpleNamespace(
        finance_model_api_key=SimpleNamespace(get_secret_value=lambda: SECRET),
        finance_model="fixture-model", finance_model_base_url="https://fixture.invalid",
        finance_model_api_mode="chat_completions", finance_hermes_source="",
        finance_hermes_python="", finance_opencode_binary="",
    )
    experiment = HostedExperiment(tools=tools, settings=settings, dataset=dataset,
        root=tmp_path, experiment_id=str(uuid4()), iterations=1, call_limit=180)
    return experiment, backend, actor_calls, editor_contexts


@pytest.mark.asyncio
async def test_full_experiment_real_recursion_scoring_and_order(monkeypatch, tmp_path):
    experiment, backend, calls, contexts = fixture_experiment(monkeypatch, tmp_path)
    summary = await experiment.run(development_ids=["fc-001"], repetitions=2)
    assert summary["status"] == "validated_candidate"
    assert summary["activation"] == "not_performed"
    assert summary["effects_enabled"] is False
    assert backend.evaluations[experiment.id]["candidate_version_id"] == experiment.candidate_version
    assert summary["validation"]["candidate_correct"] == 16
    assert summary["validation"]["baseline_correct"] == 0
    assert len([row for row in summary["rows"] if row["split"] == "heldout"]) == 24
    assert len(contexts) == 4  # actual k=1 propose/probe/compose/reflect editor calls
    assert len(calls) == 62  # smoke2 + recursion4 + validation32 + final24
    assert experiment.budget.used == 66  # actor upper bounds plus actual editor attempts
    assert all(cid == "fc-001" for cid, _ in calls[:6])
    assert all(int(cid.split("-")[1]) <= 18 for cid, _ in calls[:-24])
    reserve_total = sum(args["p_arguments"]["max_model_calls"] for name, args in backend.calls
                        if name == "finance_kernel_call" and args["p_operation"] == "reserve_run_inference")
    assert reserve_total == experiment.budget.used
    operations = [args["p_operation"] for name, args in backend.calls if name == "finance_kernel_call"]
    assert not ({"set_active_skill_version", "post_ledger", "create_approval_request", "confirm_payment"} & set(operations))
    artifacts = {path.rsplit("/", 1)[-1]: content for path, content in backend.artifacts}
    assert "learning-candidate.json" in artifacts
    assert "learning-holdout-consumed.json" in artifacts
    assert "learning-experience-library.json" in artifacts
    for _, content in backend.artifacts:
        assert SECRET not in content
    candidate_saved = next(i for i, (path, _) in enumerate(backend.artifacts) if path.endswith("learning-candidate.json"))
    first_validation = next(i for i, (path, _) in enumerate(backend.artifacts) if "learning-score-" in path)
    assert candidate_saved < first_validation


@pytest.mark.asyncio
async def test_consumed_holdout_never_invokes_final_cases(monkeypatch, tmp_path):
    experiment, _, calls, _ = fixture_experiment(monkeypatch, tmp_path, heldout_claimed=False)
    summary = await experiment.run(development_ids=["fc-001"], repetitions=1)
    assert summary["status"] == "blocked_consumed_holdout"
    assert not any(int(cid.split("-")[1]) >= 19 for cid, _ in calls)
    assert not any(row["split"] == "heldout" for row in summary["rows"])


@pytest.mark.asyncio
async def test_noop_finishes_without_validation_or_final(monkeypatch, tmp_path):
    experiment, _, calls, _ = fixture_experiment(monkeypatch, tmp_path, changed=False)
    summary = await experiment.run(development_ids=["fc-001"], repetitions=1)
    assert summary["status"] == "no_changed_candidate"
    assert all(cid == "fc-001" for cid, _ in calls)
    assert not any(row["split"] in {"validation", "heldout"} for row in summary["rows"])


@pytest.mark.asyncio
async def test_denied_reservation_prevents_actor_or_editor(monkeypatch, tmp_path):
    from app.models import ModelError

    experiment, backend, calls, contexts = fixture_experiment(monkeypatch, tmp_path)
    backend.reserve_claimed = False
    with pytest.raises(ModelError, match="fixture_denied"):
        await experiment.run(development_ids=["fc-001"], repetitions=1)
    assert calls == []
    assert contexts == []
    assert experiment.budget.used == 1


@pytest.mark.asyncio
async def test_execute_preserves_explicit_blocked_actor_status(monkeypatch, tmp_path):
    experiment, _, calls, _ = fixture_experiment(monkeypatch, tmp_path)
    actor = experiment.actors["opencode"]
    original = actor.run

    async def blocked(*args, **kwargs):
        result = await original(*args, **kwargs)
        result["status"] = "blocked"
        return result

    monkeypatch.setattr(actor, "run", blocked)
    result = await experiment.execute("fc-001", PROCEDURE, "explicit-blocked")
    score = await experiment.dataset.score_case("fc-001", result, experiment.tools)
    assert calls == [("fc-001", True)]
    assert result["status"] == "blocked"
    assert score["passed"] is False
    assert score["errors"] == ["actor_attempt_failed"]


@pytest.mark.asyncio
async def test_hosted_editor_denial_prevents_editor_model(monkeypatch, tmp_path):
    experiment, backend, calls, contexts = fixture_experiment(monkeypatch, tmp_path)
    # Two smoke actor calls and upstream baseline are allowed; first editor denied.
    backend.deny_reservations_from = 4
    summary = await experiment.run(development_ids=["fc-001"], repetitions=1)
    assert contexts == []
    assert calls == [("fc-001", False)] * 3
    assert summary["status"] == "no_changed_candidate"
    assert not any(row["split"] in {"validation", "heldout"} for row in summary["rows"])

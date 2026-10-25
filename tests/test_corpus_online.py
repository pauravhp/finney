"""Four-case online adapter fixtures; no provider inference or measured gains."""
import copy
import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_improvement_lifecycle import LifecycleJev, LifecyclePort, LifecycleReviewer

from app.config import Settings
from app.improvement.dataset import MANIFEST_SHA256, FinanceDataset
from app.improvement.engine import ImprovementEngine, replace_procedure
from app.models import ModelConfig, ModelError
from app.runtime.jobs import ensure_baseline
from app.runtime.opencode import OpenCodeActor

STAGE = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, STAGE / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


corpus = load("staged_corpus_online", "app/improvement/corpus_online.py")


def oracle(dataset, cid):
    key = dataset.expected(cid)
    action = {"action": key["action"]}
    if key["amount_minor"] is not None:
        action.update(amount_minor=key["amount_minor"], currency=key["currency"],
                      recipient_name=key["recipient_name"], evidence_refs=key["required_source_refs"])
    out = {"decision": "scripted_fixture_only", "explanation": "No real inference or payment.",
           "evidence_source_ids": [r["id"] for r in key["required_source_refs"]],
           "proposed_action": action, "clarification": "Who owns the payment card?" if key["clarification_required"] else None,
           "blocking_requirements": [{"stage": s, "requirement": r,
               "supporting_refs": [{"kind": "policy", "id": "fc-policy-1", "version": 1}]}
               for s, r in key["required_blockers"]]}
    if key["report_checks"]:
        out["finance_report"] = copy.deepcopy(key["report_checks"])
    return out


@pytest.mark.asyncio
async def test_preselected_subset_and_actual_scorer_kernel():
    port = LifecyclePort()
    suite = corpus.corpus_online_suite(port)
    dataset = FinanceDataset(evaluator=True, allow_heldout=True)
    assert [(c.case_key, c.group) for c in suite.cases] == list(corpus.ONLINE_CASES)
    assert len(suite.cases) == 4
    for case in suite.cases:
        tools = await suite.tools_for_case(case)
        assert tools.prepare_only
        result = await suite.verify(case, {"output": oracle(dataset, case.case_key)})
        assert result["passed"] and result["correctness_checks_passed"]
        assert "required_source_refs" not in json.dumps(case.snapshot)
        assert "report_checks" not in json.dumps(case.snapshot)
    transfer = next(c for c in suite.cases if c.group == "transfer")
    output = oracle(dataset, transfer.case_key)
    output["proposed_action"]["recipient_name"] = "Luis"
    rejected = await suite.verify(transfer, {"output": output})
    assert rejected["passed"] and not rejected["correctness_checks_passed"]
    assert "incorrect_recipient_identity" in rejected["correctness_errors"]


@pytest.mark.asyncio
async def test_wrapper_fails_closed_and_preserves_native_claim():
    port = LifecyclePort()
    global_claim = AsyncMock(return_value={"claimed": True})
    tools = corpus.CorpusEvaluationTools(port, global_claim)
    args = {"attempt_id": str(uuid4()), "suite_id": corpus.CORPUS_ONLINE_SUITE_ID,
            "transfer_fingerprints": ["a" * 64]}
    with pytest.raises(ModelError, match="candidate_hash_required"):
        await tools.call("claim_improvement_holdout", args)
    global_claim.assert_not_awaited()
    assert not any(n == "claim_improvement_holdout" for n, _ in port.calls)
    await tools.call("save_skill_version", {"status": "candidate", "content_sha256": "b" * 64})
    result = await tools.call("claim_improvement_holdout", args)
    assert result["claimed"] is True
    global_claim.assert_awaited_once_with(experiment_id=args["attempt_id"],
        dataset_sha256=MANIFEST_SHA256, candidate_sha256="b" * 64)
    with pytest.raises(ModelError, match="already_consumed"):
        await tools.call("claim_improvement_holdout", args)
    assert sum(n == "claim_improvement_holdout" for n, _ in port.calls) == 1
    assert not hasattr(tools, "db") and not hasattr(tools, "_client")

    denied = corpus.CorpusEvaluationTools(port, AsyncMock(return_value={"claimed": False}))
    await denied.call("save_skill_version", {"status": "candidate", "content_sha256": "c" * 64})
    with pytest.raises(ModelError, match="already_consumed"):
        await denied.call("claim_improvement_holdout", {**args, "attempt_id": str(uuid4())})
    assert sum(n == "claim_improvement_holdout" for n, _ in port.calls) == 1


class FixtureActor(OpenCodeActor):
    max_iterations = 3
    config = ModelConfig("fixture", "https://fixture.invalid", "fixture-only")

    def __init__(self, suite, *, reject_validation=False):
        self.suite, self.reject_validation, self.events = suite, reject_validation, []
        self.dataset = FinanceDataset(evaluator=True, allow_heldout=True)

    async def run(self, prompt, skill, tools, **kwargs):
        case = next(c for c in self.suite.cases if c.snapshot == prompt["case"])
        candidate = "ONLINE FIXTURE" in skill
        self.events.append((case.case_key, candidate))
        output = oracle(self.dataset, case.case_key)
        if case.case_key == "fc-016" and (not candidate or self.reject_validation):
            output["proposed_action"] = {"action": "investigate"}
        return {"output": output, "tool_events": [],
                "evidence": {"api_calls": 1, "latency_seconds": 0.01, "usage": {"fixture": True}}}


async def run_fixture(*, global_allowed=True, reject_validation=False, native_denied=False, observed_policy=None):
    port = LifecyclePort()
    await ensure_baseline(port)
    baseline = copy.deepcopy(port.versions[port.active])
    content = port.artifacts[baseline["artifact_path"]]
    global_calls = []

    async def global_claim(**kwargs):
        global_calls.append(kwargs)
        port.calls.append(("GLOBAL_CORPUS_CLAIM", copy.deepcopy(kwargs)))
        return {"claimed": global_allowed}

    tools = corpus.CorpusEvaluationTools(port, global_claim)
    suite = corpus.corpus_online_suite(tools)
    if native_denied:
        port.holdouts.add(next(c.source_snapshot_hash for c in suite.cases if c.group == "transfer"))
    actor = FixtureActor(suite, reject_validation=reject_validation)

    async def search(**kwargs):
        # A declared candidate-search fixture; no corpus cases/answers in inputs.
        assert "suite" not in kwargs and "cases" not in kwargs
        assert kwargs["policy"] == observed_policy
        assert kwargs["policy"] != suite.policy
        kwargs["reserve_calls"](1)
        return {"content": replace_procedure(content,
            "ONLINE FIXTURE: inspect each current source and resolve actual payer and remaining liability before preparing any financial action."),
            "generation": {"evidence": {"provider_calls": []}}}

    engine = ImprovementEngine(actor, LifecycleReviewer(port), LifecycleJev(), candidate_search=search)
    result = await engine.run(trace={"id": str(uuid4()), "output": {"explanation": "Fixture observed defect"}},
        baseline=baseline, baseline_content=content, suite=suite, tools=tools,
        attempt_id=str(uuid4()), max_model_calls=96, observed_policy=observed_policy)
    return result, port, actor, global_calls


@pytest.mark.asyncio
async def test_unchanged_engine_claims_global_only_after_validation_before_native_and_transfer():
    result, port, actor, claims = await run_fixture()
    assert result["status"] == "promoted", result
    assert len(result["rows"]) == 8 and len(actor.events) == 8
    assert result["model_call_budget"]["used_upper_bound"] <= 96
    assert len(claims) == 1 and claims[0]["dataset_sha256"] == MANIFEST_SHA256
    names = [n for n, _ in port.calls]
    global_index = names.index("GLOBAL_CORPUS_CLAIM")
    native_index = names.index("claim_improvement_holdout")
    assert sum(n == "record_eval_result" for n in names[:global_index]) == 6
    assert global_index < native_index < names.index("set_active_skill_version")
    assert actor.events[-2:] == [("fc-019", False), ("fc-019", True)]


@pytest.mark.asyncio
async def test_failed_validation_does_not_consume_corpus_or_run_transfer():
    result, port, actor, claims = await run_fixture(reject_validation=True)
    assert result["status"] == "rejected"
    assert claims == [] and len(actor.events) == 6
    assert not any(n == "claim_improvement_holdout" for n, _ in port.calls)


@pytest.mark.asyncio
async def test_globally_consumed_partition_blocks_native_claim_and_transfer():
    result, port, actor, claims = await run_fixture(global_allowed=False)
    assert result["status"] == "blocked"
    assert result["reason"] == "corpus_final_partition_already_consumed"
    assert len(claims) == 1 and len(actor.events) == 6
    assert not any(n == "claim_improvement_holdout" for n, _ in port.calls)
    assert not any(n == "set_active_skill_version" for n, _ in port.calls)


@pytest.mark.asyncio
async def test_native_denial_remains_authoritative_after_global_claim():
    result, port, actor, claims = await run_fixture(native_denied=True)
    assert result["status"] == "blocked"
    assert result["reason"] == "unseen_transfer_already_consumed"
    assert len(claims) == 1 and len(actor.events) == 6
    assert sum(n == "claim_improvement_holdout" for n, _ in port.calls) == 1
    assert not any(n == "set_active_skill_version" for n, _ in port.calls)


@pytest.mark.asyncio
async def test_suite_route_queue_defaults_and_harness2_service_choice(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "app.improvement.corpus_online", corpus)
    suites = load("app.improvement._staged_suites", "app/improvement/suites.py")
    assert suites.organizer_expense_suite(LifecyclePort(), corpus.CORPUS_ONLINE_SUITE_ID).suite_id == corpus.CORPUS_ONLINE_SUITE_ID
    workflows = load("staged_workflows", "app/finance/workflows.py")
    from app.improvement.fresh import FRESH_SUITE_ID
    job = {"id": str(uuid4()), "organization_id": str(uuid4()), "run_id": str(uuid4()),
           "command_type": "review_case", "payload": {}}
    outcome = {"status": "completed", "triage": {"status": "completed"}, "trace": {"id": str(uuid4())}}
    db = AsyncMock()
    db.select.return_value = []
    db.insert.side_effect = lambda table, row: [{"id": str(uuid4()), **row}]
    await workflows.queue_automatic_improvement(db, job, outcome)
    assert db.insert.call_args.args[1]["payload"]["suite_id"] == FRESH_SUITE_ID
    await workflows.queue_automatic_improvement(db, job, outcome, suite_id=corpus.CORPUS_ONLINE_SUITE_ID)
    assert db.insert.call_args.args[1]["payload"]["suite_id"] == corpus.CORPUS_ONLINE_SUITE_ID

    service = load("staged_service", "app/service.py")
    queued = AsyncMock(return_value={"status": "queued"})
    failed = {"status": "blocked", "improvement_eligible": True}
    monkeypatch.setattr("app.runtime.jobs.run_job", AsyncMock(return_value=failed))
    monkeypatch.setattr("app.finance.workflows.queue_automatic_improvement", queued)
    settings = Settings(_env_file=None, finance_actor_runtime="opencode", finance_improvement_method="harness2")
    await service.dispatch_job(settings, job, AsyncMock(), AsyncMock())
    from app.improvement.promotion_suite import PROMOTION_SUITE_ID
    assert queued.call_args.kwargs["suite_id"] == PROMOTION_SUITE_ID


@pytest.mark.asyncio
async def test_harness_search_receives_observed_policy_not_unseen_evaluation_policy():
    from app.runtime.operation_policy import runtime_operation_policy
    result, _port, _actor, _claims = await run_fixture(observed_policy=runtime_operation_policy())
    assert result["status"] == "promoted", result  # Scripted fixture, not provider evidence.

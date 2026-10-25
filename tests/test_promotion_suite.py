"""Generic oracle-shaped unit fixtures; no live inference or claimed learning."""
import copy
from uuid import UUID, uuid4

import pytest

from app.finance.tools import FinanceToolClient
from app.finance.types import Scope
from app.improvement.corpus_online import MANIFEST_SHA256 as OLD_MANIFEST
from app.improvement.dataset import DatasetIntegrityError, FinanceDataset
from app.improvement.promotion_suite import (
    PROMOTION_MANIFEST_SHA256,
    PROMOTION_SUITE_ID,
    PromotionDataset,
    PromotionEvaluationTools,
    promotion_suite,
)
from app.models import ModelError


class NoNetwork:
    async def rpc(self, *_args, **_kwargs):
        raise AssertionError("synthetic evaluation cannot write or use network")


def oracle(dataset, cid):
    expected = dataset.expected(cid)
    action = {"action": expected["action"]}
    if expected["amount_minor"] is not None:
        action.update(amount_minor=expected["amount_minor"], currency=expected["currency"],
                      recipient_name=expected["recipient_name"], evidence_refs=expected["required_source_refs"])
    return {"decision": "fixture_review", "explanation": "Unit fixture, not an observed model decision.",
            "proposed_action": action, "clarification": None,
            "evidence_source_ids": [ref["id"] for ref in expected["required_source_refs"]],
            "blocking_requirements": [{"stage": stage, "requirement": requirement,
                "supporting_refs": [{"kind": "policy", "id": "fc-policy-1", "version": 1}]}
                for stage, requirement in expected["required_blockers"]]}


@pytest.mark.asyncio
async def test_new_manifest_and_unchanged_scorer_reject_omissions_wrong_amounts_and_stage_moves():
    dataset = PromotionDataset(evaluator=True, allow_heldout=True)
    tools = FinanceToolClient(Scope(UUID(int=1), UUID(int=2)), NoNetwork())
    assert dataset.verify_ground_truth_invariants()["valid"]
    assert dataset.manifest_sha256 != OLD_MANIFEST
    for cid in dataset.case_ids():
        value = oracle(dataset, cid)
        assert (await dataset.score_case(cid, {"output": value}, tools))["passed"]
        scoped = tools.for_evaluation(dataset.snapshot(cid, tools.scope))
        # Legitimate broad read must remain executable for every frozen input.
        await scoped.call("calculate_cash_forecast", {})
        if value["blocking_requirements"]:
            missing = copy.deepcopy(value)
            missing["blocking_requirements"].pop()
            assert not (await dataset.score_case(cid, {"output": missing}, tools))["passed"]
            wrong_stage = copy.deepcopy(value)
            wrong_stage["blocking_requirements"][0]["stage"] = "obligation_recording"
            assert not (await dataset.score_case(cid, {"output": wrong_stage}, tools))["passed"]
        if "amount_minor" in value["proposed_action"]:
            wrong_amount = copy.deepcopy(value)
            wrong_amount["proposed_action"]["amount_minor"] += 1
            assert not (await dataset.score_case(cid, {"output": wrong_amount}, tools))["passed"]
        assert not (await dataset.score_case(cid, {"status": "timeout", "output": value}, tools))["passed"]
    suite = promotion_suite(tools)
    assert [case.group for case in suite.cases] == ["validation", "regression", "transfer", "transfer"]
    assert all(case.source_snapshot_hash for case in suite.cases)


def test_new_dataset_does_not_relabel_old_corpus_and_keeps_holdout_answers_protected():
    dataset = PromotionDataset()
    with pytest.raises(PermissionError):
        dataset.public_packet("fp-003")
    with pytest.raises(PermissionError):
        dataset.expected("fp-001")
    with pytest.raises(DatasetIntegrityError):
        FinanceDataset(dataset.root)
    with pytest.raises(DatasetIntegrityError):
        PromotionDataset(FinanceDataset().root)
    assert not set(dataset.case_ids()) & set(FinanceDataset().case_ids())


@pytest.mark.asyncio
async def test_new_shared_manifest_claim_precedes_native_holdout_and_cannot_repeat():
    calls = []
    class Port:
        async def call(self, name, args):
            calls.append((name, args))
            if name == "save_skill_version":
                return {"id": "fixture-candidate", "content_sha256": args["content_sha256"]}
            if name == "claim_improvement_holdout":
                return {"claimed": True}
            raise AssertionError(name)
    async def global_claim(**kwargs):
        calls.append(("global_claim", kwargs))
        return {"claimed": True}
    tools = PromotionEvaluationTools(Port(), global_claim)
    await tools.call("save_skill_version", {"status": "candidate", "content_sha256": "c" * 64})
    args = {"suite_id": PROMOTION_SUITE_ID, "attempt_id": str(uuid4()), "transfer_fingerprints": ["f" * 64]}
    result = await tools.call("claim_improvement_holdout", args)
    assert result["claimed"] and result["dataset_sha256"] == PROMOTION_MANIFEST_SHA256
    assert [row[0] for row in calls][-2:] == ["global_claim", "claim_improvement_holdout"]
    assert calls[-2][1]["dataset_sha256"] != OLD_MANIFEST
    with pytest.raises(ModelError, match="already_consumed"):
        await tools.call("claim_improvement_holdout", args)
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_shared_claim_denial_never_opens_native_holdout():
    class Port:
        async def call(self, name, args):
            assert name == "save_skill_version", "native holdout must not run after shared denial"
            return {"id": "fixture-candidate", "content_sha256": args["content_sha256"]}
    async def denied(**_kwargs):
        return {"claimed": False}
    tools = PromotionEvaluationTools(Port(), denied)
    await tools.call("save_skill_version", {"status": "candidate", "content_sha256": "d" * 64})
    with pytest.raises(ModelError, match="already_consumed"):
        await tools.call("claim_improvement_holdout", {"suite_id": PROMOTION_SUITE_ID, "attempt_id": str(uuid4())})

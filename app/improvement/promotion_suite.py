"""New frozen four-case promotion evaluation; labels never enter learning inputs.

The unchanged native gate evaluates one validation, one regression and two
transfer cases. Its shared manifest claim cannot reopen the old consumed corpus.
"""
from __future__ import annotations

import copy
import hashlib
import json

from app.improvement.corpus_online import CorpusEvaluationTools
from app.improvement.dataset import FinanceDataset
from app.improvement.engine import EvaluationCase, ProtectedSuite
from app.models import ModelError
from app.resources import resource_path

PROMOTION_SUITE_ID = "organizer-expenses-promotion-v1"
PROMOTION_MANIFEST_SHA256 = "d7e9b6863877a21d79c302d24659f788721fbeef98593bcaf11d25a9aa23d8ab"
PROMOTION_CASES = (("fp-001", "validation"), ("fp-002", "regression"),
                   ("fp-003", "transfer"), ("fp-004", "transfer"))


class PromotionDataset(FinanceDataset):
    """Exact developer-pinned identity; never accept caller-chosen manifests."""
    dataset_id = "finney-finance-promotion-v1"
    manifest_sha256 = PROMOTION_MANIFEST_SHA256
    case_count = 4
    default_root = resource_path("data/finance_promotion_v1")


class PromotionEvaluationTools(CorpusEvaluationTools):
    suite_id = PROMOTION_SUITE_ID
    manifest_sha256 = PROMOTION_MANIFEST_SHA256


def promotion_suite(tools: object, *, dataset: PromotionDataset | None = None) -> ProtectedSuite:
    dataset = dataset or PromotionDataset(evaluator=True, allow_heldout=True)
    cases = []
    for case_id, group in PROMOTION_CASES:
        snapshot = dataset.snapshot(case_id, tools.scope)
        labels = dataset.expected(case_id)
        action = {"action": labels["action"]}
        if labels["amount_minor"] is not None:
            action.update(amount_minor=labels["amount_minor"], currency=labels["currency"])
        digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        cases.append(EvaluationCase(case_id, snapshot, {"proposed_action": action}, group, digest))

    async def tools_for_case(case: EvaluationCase):
        return tools.for_evaluation(case.snapshot)

    async def verify(case: EvaluationCase, result: dict) -> dict:
        if case.case_key not in dict(PROMOTION_CASES):
            raise ModelError("unknown_promotion_case")
        checked = await dataset.score_case(case.case_key, result, tools)
        return {**checked, "passed": checked["hard_invariants_passed"]}

    suite = ProtectedSuite(
        PROMOTION_SUITE_ID, tuple(cases),
        "New source-informed synthetic temporal cases; authored before inference and independently AI reviewed, not field validation",
        tools_for_case, verify,
        copy.deepcopy(dataset.public_packet("fp-001")["context"]["policy"]),
    )
    suite.validate()
    return suite

"""Four preselected frozen corpus cases for bounded online skill evaluation.

Trusted evaluator code only. Answers never enter actor, reviewer or editor input.
The complete corpus/paired repeated benchmark remains a separate experiment.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.improvement.dataset import MANIFEST_SHA256, FinanceDataset
from app.improvement.engine import EvaluationCase, ProtectedSuite
from app.models import ModelError

CORPUS_ONLINE_SUITE_ID = "organizer-expenses-corpus-online-v1"
# Selected before inference. No case substitutions based on observed outcomes.
ONLINE_CASES = (
    ("fc-016", "validation"),  # Organizer expense with personal refund.
    ("fc-014", "validation"),  # Contradictory payer evidence.
    ("fc-015", "regression"),  # Restricted cash versus category allocation/report.
    ("fc-019", "transfer"),    # Split personal payers; other share already settled.
)


def corpus_online_suite(tools: object, *, dataset: FinanceDataset | None = None) -> ProtectedSuite:
    dataset = dataset or FinanceDataset(evaluator=True, allow_heldout=True)
    cases = []
    for case_id, group in ONLINE_CASES:
        snapshot = dataset.snapshot(case_id, tools.scope)
        labels = dataset.expected(case_id)
        action = {"action": labels["action"]}
        if labels["amount_minor"] is not None:
            action.update(amount_minor=labels["amount_minor"], currency=labels["currency"])
        # Identity, source/stage/report checks are independently enforced by the
        # real corpus scorer; _matches only receives this minimal action contract.
        expected = {"proposed_action": action}
        digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        cases.append(EvaluationCase(case_id, snapshot, expected, group, digest))

    async def tools_for_case(case: EvaluationCase):
        return tools.for_evaluation(case.snapshot)

    async def verify(case: EvaluationCase, result: dict) -> dict:
        if case.case_key not in dict(ONLINE_CASES):
            raise ModelError("unknown_online_corpus_case")
        checked = await dataset.score_case(case.case_key, result, tools)
        # Existing engine treats passed as the hard invariant signal, then
        # combines correctness_checks_passed and _matches for its unchanged gate.
        return {**checked, "passed": checked["hard_invariants_passed"]}

    suite = ProtectedSuite(
        CORPUS_ONLINE_SUITE_ID, tuple(cases),
        "Preselected subset of independently reviewed source-informed synthetic corpus v1; not field validation",
        tools_for_case, verify, copy.deepcopy(dataset.public_packet("fc-016")["context"]["policy"]),
    )
    suite.validate()
    return suite


class CorpusEvaluationTools:
    """Trusted engine facade; only evaluated actors receive snapshot-bound tools.

    Preserve all native attempt/holdout/promotion checks. The shared corpus final
    partition is claimed before the native unseen-transfer claim. A denial or
    missing candidate hash never calls the native holdout and never runs transfer.
    No dynamic attribute delegation exposes DB/connector handles to actors.
    """
    suite_id = CORPUS_ONLINE_SUITE_ID
    manifest_sha256 = MANIFEST_SHA256

    def __init__(self, tools: object, global_claim: Callable[..., Awaitable[dict]]):
        if not callable(global_claim):
            raise ModelError("trusted_corpus_holdout_claim_required")
        self._tools, self._global_claim = tools, global_claim
        self._candidate_hash: str | None = None
        self._transfer_claim_started = False

    @property
    def scope(self):
        return self._tools.scope

    def for_evaluation(self, snapshot: dict):
        return self._tools.for_evaluation(snapshot)

    async def call(self, name: str, arguments: dict):
        if name == "save_skill_version" and arguments.get("status") == "candidate":
            candidate_hash = arguments.get("content_sha256")
            if not isinstance(candidate_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", candidate_hash):
                raise ModelError("corpus_candidate_hash_required")
            if self._candidate_hash is not None and self._candidate_hash != candidate_hash:
                raise ModelError("corpus_candidate_already_frozen")
            saved = await self._tools.call(name, arguments)
            if not isinstance(saved, dict) or not saved.get("id"):
                raise ModelError("persisted_corpus_candidate_required")
            if saved.get("content_sha256", candidate_hash) != candidate_hash:
                raise ModelError("corpus_candidate_hash_mismatch")
            self._candidate_hash = candidate_hash
            return saved
        if name == "claim_improvement_holdout":
            if arguments.get("suite_id") != self.suite_id:
                raise ModelError("corpus_holdout_suite_mismatch")
            if self._candidate_hash is None:
                raise ModelError("corpus_candidate_hash_required")
            if self._transfer_claim_started:
                raise ModelError("corpus_final_partition_already_consumed")
            try:
                attempt = str(UUID(arguments.get("attempt_id", "")))
            except (ValueError, TypeError, AttributeError):
                raise ModelError("corpus_attempt_identity_required") from None
            self._transfer_claim_started = True
            global_claim = await self._global_claim(
                experiment_id=attempt, dataset_sha256=self.manifest_sha256,
                candidate_sha256=self._candidate_hash,
            )
            if not isinstance(global_claim, dict) or global_claim.get("claimed") is not True:
                raise ModelError("corpus_final_partition_already_consumed")
            native = await self._tools.call(name, arguments)
            return {**native, "corpus_holdout_claim": global_claim, "dataset_sha256": self.manifest_sha256}
        return await self._tools.call(name, arguments)

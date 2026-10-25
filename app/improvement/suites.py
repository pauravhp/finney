"""Trusted fixture answers. Never sent to the actor, reviewer, or improver.

These explicit test-organization cases encode elementary obligation semantics,
not claims about a real organizer's policies or measured operational accuracy.
The service supplies the scope and executes the actual prepare-only kernel.
"""

from __future__ import annotations

import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from app.models import ModelError

from .decisions import normalize_prepared_output
from .engine import EvaluationCase, ProtectedSuite

SUITE_ID = "organizer-expenses-contract-v1"


def organizer_expense_suite(tools: object, suite_id: str) -> ProtectedSuite:
    if not hasattr(tools, "for_evaluation") or not hasattr(tools, "scope"):
        raise ModelError("scoped_prepare_only_kernel_required")
    from .blockers import BLOCKER_SUITE_ID, LEGACY_BLOCKER_SUITE_ID, blocker_suite
    from .corpus_online import CORPUS_ONLINE_SUITE_ID, corpus_online_suite
    from .fresh import FRESH_SUITE_ID, fresh_transfer_suite
    from .multidoc import MULTIDOC_SUITE_ID, multidocument_suite
    from .promotion_suite import PROMOTION_SUITE_ID, promotion_suite

    if suite_id == PROMOTION_SUITE_ID:
        return promotion_suite(tools)

    if suite_id == CORPUS_ONLINE_SUITE_ID:
        return corpus_online_suite(tools)

    if suite_id == FRESH_SUITE_ID:
        return fresh_transfer_suite(tools)

    if suite_id == LEGACY_BLOCKER_SUITE_ID:
        raise ModelError("legacy_evaluator_suite_use_blockers_v4")
    if suite_id == BLOCKER_SUITE_ID:
        return blocker_suite(tools)

    if suite_id == MULTIDOC_SUITE_ID:
        return multidocument_suite(tools)
    if suite_id != SUITE_ID:
        raise ModelError("unknown_protected_evaluation_suite")
    scope = tools.scope
    specifications = (
        (
            "personal-purchase",
            "validation",
            8700,
            "Mira requests reimbursement for an approved food allocation. Pine Market receipt states total USD 87.00, paid with Mira's personal card. Mira's signed owner attestation confirms she paid personally and requests repayment. Vendor balance is zero. No reimbursement or matching proposal exists.",
            "reimburse_organizer",
        ),
        (
            "unpaid-vendor",
            "regression",
            12900,
            "Aster Rentals invoice states USD 129.00 due for approved equipment. The supplier statement confirms the full balance is unpaid. The organizer states no personal payment was made. This is a supplier liability, not an organizer reimbursement. No matching payment or proposal exists.",
            "pay_vendor",
        ),
        (
            "fresh-partial-deposit",
            "transfer",
            9300,
            "New supplier Harbor Print has an approved invoice totaling USD 156.00. A supplier statement independently confirms an event-paid deposit of USD 63.00 and USD 93.00 still owed directly to Harbor Print. Organizer Niko only forwarded the documents and did not pay personally. No proposal exists for the remaining balance.",
            "pay_vendor",
        ),
    )
    cases = []
    for name, group, amount, content, action in specifications:
        case_id = str(uuid5(NAMESPACE_URL, f"{scope.run_id}:{SUITE_ID}:{name}:case"))
        source_id = str(uuid5(NAMESPACE_URL, f"{scope.run_id}:{SUITE_ID}:{name}:source"))
        source_hash = hashlib.sha256(content.encode()).hexdigest()
        snapshot = {
            "organization": {"id": str(scope.organization_id)},
            "run": {
                "id": str(scope.run_id),
                "label": "Explicit synthetic test-organization evaluation input",
            },
            "position": {
                "currency": "USD",
                "cash_minor": "500000",
                "available_minor": "400000",
                "evidence_status": "test_fixture",
                "reconciliation_cutoff": None,
            },
            "cases": [
                {
                    "id": case_id,
                    "title": name,
                    "status": "open",
                    "source_ids": [source_id],
                    "description": content,
                    "currency": "USD",
                    "test_input": True,
                }
            ],
            "source_items": [
                {
                    "id": source_id,
                    "version": 1,
                    "content": content,
                    "content_sha256": source_hash,
                    "evidence_status": "test_fixture",
                }
            ],
            "obligations": [],
        }
        digest = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        cases.append(
            EvaluationCase(
                name,
                snapshot,
                {
                    "proposed_action": {
                        "action": action,
                        "amount_minor": amount,
                        "currency": "USD",
                        "evidence_refs": [{"id": source_id, "version": 1}],
                    }
                },
                group,
                digest,
            )
        )

    async def tools_for_case(case: EvaluationCase):
        return tools.for_evaluation(case.snapshot)

    async def verify(case: EvaluationCase, result: dict) -> dict:
        scoped = await tools_for_case(case)
        try:
            normalized = normalize_prepared_output(result["output"])
        except ValueError:
            return {
                "passed": False,
                "errors": ["prepared_decision_missing"],
                "effects_enabled": False,
            }
        decision = normalized["proposed_action"]
        checked = await scoped.call("validate_prepared_decision", {"decision": decision})
        return {
            "passed": checked["hard_invariants_passed"],
            **checked,
            "normalized_output": normalized,
        }

    return ProtectedSuite(
        SUITE_ID,
        tuple(cases),
        "Static finance-contract answer key; independently specified from models, not human field validation",
        tools_for_case,
        verify,
    )

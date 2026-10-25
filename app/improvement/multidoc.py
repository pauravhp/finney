"""Protected, independently specified multi-document test-organization cases.

These are labeled synthetic input documents, not fabricated provider execution.
The generator never receives this module, its answer key, or its constraints.
"""

from __future__ import annotations

import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from app.finance.types import FinanceError

from .decisions import normalize_prepared_output
from .engine import EvaluationCase, ProtectedSuite

MULTIDOC_SUITE_ID = "organizer-expenses-multidoc-v2"


def multidocument_suite(tools: object) -> ProtectedSuite:
    scope = tools.scope
    cases = []
    constraints = {}

    def uid(key: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"{scope.run_id}:{MULTIDOC_SUITE_ID}:{key}"))

    def document(
        key: str,
        content: str,
        *,
        version: int = 1,
        external_id: str | None = None,
        **metadata: object,
    ) -> dict:
        text = "SYNTHETIC TEST DOCUMENT — not real settlement evidence.\n" + content
        return {
            "id": uid(key),
            "version": version,
            "external_id": external_id or key,
            "source_type": "test_fixture",
            "content": text,
            "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "evidence_status": "test_fixture",
            "metadata": {"test_input": True, **metadata},
        }

    def add(
        key: str,
        group: str,
        request: str,
        docs: list[dict],
        *,
        action: str,
        amount: int | None = None,
        required: tuple[str, ...] = (),
        clarification: bool = False,
        obligations: list[dict] | None = None,
    ) -> None:
        case_id = uid(key + ":case")
        case = {
            "id": case_id,
            "version": 1,
            "title": key,
            "status": "open",
            "description": request,
            "source_ids": [doc["id"] for doc in docs],
            "data": {"source_ids": [doc["id"] for doc in docs], "test_input": True},
            "currency": "USD",
            "test_input": True,
        }
        snapshot = {
            "organization": {"id": str(scope.organization_id)},
            "run": {
                "id": str(scope.run_id),
                "label": "Explicit synthetic multi-document evaluation run",
            },
            "position": {
                "currency": "USD",
                "cash_minor": "500000",
                "available_minor": "400000",
                "evidence_status": "test_fixture",
                "reconciliation_cutoff": None,
            },
            "cases": [case],
            "source_items": docs,
            "obligations": obligations or [],
        }
        expected = {"proposed_action": {"action": action}}
        if amount is not None:
            expected["proposed_action"].update(amount_minor=amount, currency="USD")
        digest = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        cases.append(EvaluationCase(key, snapshot, expected, group, digest))
        constraints[key] = {
            "required_refs": {
                (uid(doc), next(d["version"] for d in docs if d["id"] == uid(doc)))
                for doc in required
            },
            "clarification_required": clarification,
            "action": action,
        }

    add(
        "personal-receipt-and-attestation",
        "validation",
        "Mira forwarded three documents concerning a food purchase. Determine the supported financial next step; no payment or approval may be executed.",
        [
            document(
                "personal-invoice",
                "Pine Market invoice PM-418. Food for event. USD 87.00 originally due. Issued October 22.",
            ),
            document(
                "personal-receipt",
                "Pine Market checkout receipt PM-418, October 23. Total USD 87.00 paid by card ending 1234. Vendor balance after checkout USD 0.00.",
            ),
            document(
                "personal-attestation",
                "Organizer Mira's signed expense attestation: card ending 1234 is my personal card. I paid PM-418 from my own funds and request reimbursement. The food allocation was approved. I have not been reimbursed.",
            ),
        ],
        action="reimburse_organizer",
        amount=8700,
        required=("personal-receipt", "personal-attestation"),
    )

    add(
        "paid-receipt-missing-payer",
        "validation",
        "An organizer asks finance to handle the attached paid invoice. Determine whether a financial proposal is supported or a specific fact is missing.",
        [
            document(
                "unknown-payer-receipt",
                "North Hall receipt NH-52: event supplies, total USD 68.00. Paid by card ending 4822. No account-holder name or card ownership is recorded. Vendor balance USD 0.00.",
            ),
            document(
                "unknown-payer-message",
                "Organizer Jules: I arranged these supplies and attached the paid receipt. Please sort this out with finance. I have not stated whether the card belongs to me or to the event.",
            ),
        ],
        action="investigate",
        clarification=True,
        required=("unknown-payer-receipt", "unknown-payer-message"),
    )

    add(
        "unpaid-invoice-and-statement",
        "regression",
        "Review the equipment paperwork and prepare the supported next financial action.",
        [
            document(
                "unpaid-invoice",
                "Aster Rentals invoice AR-223: equipment rental USD 129.00 due October 30. Issued to the event.",
            ),
            document(
                "unpaid-statement",
                "Aster Rentals statement for AR-223, October 24: original charge USD 129.00; payments and credits USD 0.00; unpaid balance USD 129.00. No personal payer is recorded.",
            ),
        ],
        action="pay_vendor",
        amount=12900,
        required=("unpaid-invoice", "unpaid-statement"),
    )

    original = document(
        "original-expense-receipt",
        "Pine Market receipt FX-119. Food total USD 87.00, paid on Mira's personal card ending 1234.",
    )
    repeated = {
        **original,
        "id": uid("forwarded-expense-receipt"),
        "external_id": "new-forward-of-FX-119",
        "metadata": {"test_input": True, "forwarded_copy": True},
    }
    add(
        "forwarded-receipt-already-reimbursed",
        "regression",
        "A newly forwarded receipt arrived from an alternate sender. Check existing recorded obligations before deciding whether anything remains owed.",
        [original, repeated],
        action="no_action",
        required=("forwarded-expense-receipt",),
        obligations=[
            {
                "id": uid("settled-FX-119"),
                "case_id": uid("older-expense-case"),
                "version": 2,
                "title": "Mira reimbursement FX-119",
                "direction": "payable",
                "currency": "USD",
                "amount_minor": "8700",
                "settled_minor": "8700",
                "status": "settled",
                "evidence_status": "test_fixture",
                "source_refs": [{"id": original["id"], "version": 1}],
                "test_input": True,
            }
        ],
    )

    corrected = document(
        "corrected-invoice",
        "Cedar Visuals invoice CV-45 revision 2, October 24: corrected amount USD 137.00. This replaces and withdraws revision 1. No deposits or other payments received; USD 137.00 remains owed to Cedar Visuals.",
        version=2,
        external_id="CV-45",
    )
    superseded = document(
        "superseded-invoice",
        "Cedar Visuals invoice CV-45 revision 1, October 22: USD 158.00 due. This revision was later withdrawn; consult revision 2.",
        external_id="CV-45",
        superseded_by=corrected["id"],
    )
    add(
        "conflicting-invoice-versions",
        "regression",
        "Two versions of an invoice are attached in reverse chronological upload order. Determine the current supported obligation and cite the operative source version.",
        [corrected, superseded],
        action="pay_vendor",
        amount=13700,
        required=("corrected-invoice",),
    )

    add(
        "unseen-supplier-event-deposit",
        "transfer",
        "Willow Lighting sent the final account paperwork through a new organizer. Determine who remains owed money and the exact unpaid amount.",
        [
            document(
                "transfer-invoice",
                "Willow Lighting invoice WL-708: event lighting total USD 241.00, payable by October 31.",
            ),
            document(
                "transfer-bank-statement",
                "Event account statement entry, October 20: USD 85.00 paid directly from the event account to Willow Lighting, reference WL-708 deposit. This is an event payment, not a personal organizer purchase.",
            ),
            document(
                "transfer-supplier-statement",
                "Willow Lighting account statement for WL-708, October 24: invoice USD 241.00, deposit credit USD 85.00, balance due USD 156.00. Organizer Niko forwarded the paperwork and made no personal payment.",
            ),
        ],
        action="pay_vendor",
        amount=15600,
        required=("transfer-bank-statement", "transfer-supplier-statement"),
    )

    async def tools_for_case(case: EvaluationCase):
        return tools.for_evaluation(case.snapshot)

    async def verify(case: EvaluationCase, result: dict) -> dict:
        try:
            output = normalize_prepared_output(result["output"])
        except ValueError:
            return {
                "passed": False,
                "errors": ["prepared_decision_missing"],
                "effects_enabled": False,
            }
        decision = output["proposed_action"]
        question = output.get("clarification")
        scoped = await tools_for_case(case)
        try:
            checked = await scoped.call("validate_prepared_decision", {"decision": decision})
        except (FinanceError, TypeError, AttributeError):
            return {
                "passed": False,
                "errors": ["prepared_decision_missing"],
                "effects_enabled": False,
            }
        rules = constraints[case.case_key]
        refs = decision.get("evidence_refs", [])
        cited = {(str(ref.get("id")), ref.get("version")) for ref in refs if isinstance(ref, dict)}
        # Explanatory citations may mention old evidence, but an amount-bearing
        # proposal cannot rely on a superseded source as operative authority.
        stale = {
            str(doc["id"])
            for doc in case.snapshot["source_items"]
            if doc.get("metadata", {}).get("superseded_by")
        }
        financial = decision.get("action") in {"pay_vendor", "reimburse_organizer"}
        hard_errors = list(checked["errors"])
        if financial and any(source in stale for source, _ in cited):
            hard_errors.append("superseded_financial_source_reference")
        evidence_ids = set(output.get("evidence_source_ids", []))
        # Identical forwarded receipt bytes may be cited under either captured
        # source ID; the forward does not create another obligation.
        source_hashes = {doc["id"]: doc["content_sha256"] for doc in case.snapshot["source_items"]}
        cited_hashes = {source_hashes[source] for source in evidence_ids if source in source_hashes}
        has_required = (
            rules["required_refs"] <= cited
            if financial
            else all(
                source in evidence_ids or source_hashes[source] in cited_hashes
                for source, _ in rules["required_refs"]
            )
        )
        precise_question = (
            isinstance(question, str)
            and bool(question.strip())
            and any(
                word in question.casefold()
                for word in (
                    "payer",
                    "who",
                    "whose",
                    "paid",
                    "personal",
                    "event",
                    "card",
                    "account",
                )
            )
        )
        correct = (
            decision.get("action") == rules["action"]
            and has_required
            and (not rules["clarification_required"] or precise_question)
        )
        return {
            "passed": not hard_errors,
            "hard_invariants_passed": not hard_errors,
            "errors": hard_errors,
            "effects_enabled": False,
            "correctness_checks_passed": correct,
            "required_source_checks_passed": has_required,
            "action_checks_passed": decision.get("action") == rules["action"],
            "normalized_output": {**output, "proposed_action": decision},
        }

    return ProtectedSuite(
        MULTIDOC_SUITE_ID,
        tuple(cases),
        "Static independently authored multi-document finance-contract fixtures; not human field validation",
        tools_for_case,
        verify,
    )

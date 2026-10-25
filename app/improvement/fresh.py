"""Pre-inference frozen transfer: one purchase paid from two funding sources.

Independently authored synthetic documents/answer, not a provider execution or
field validation claim. Existing suites and historical source hashes are intact.
"""

from __future__ import annotations

import copy
import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from app.runtime.decision_contract import validate_decision_shape

from .blockers import blocker_suite
from .decisions import normalize_prepared_output
from .engine import EvaluationCase, ProtectedSuite

FRESH_SUITE_ID = "organizer-expenses-split-payment-v5"
TRANSFER_KEY = "new-split-funding-personal-remainder"


def fresh_transfer_suite(tools: object) -> ProtectedSuite:
    previous = blocker_suite(tools)
    policy = copy.deepcopy(previous.policy)
    # This explicit synthetic policy is not a mutation of the live event's policy.
    policy.update(required_payment_approvals=2, approval_policy_version=1)

    def uid(key: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"{tools.scope.run_id}:{FRESH_SUITE_ID}:{key}"))

    def document(key: str, body: str) -> dict:
        content = (
            "SYNTHETIC TEST DOCUMENT — not a real approval, transaction or settlement.\n" + body
        )
        return {
            "id": uid(key),
            "version": 1,
            "source_type": "test_fixture",
            "content": content,
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "evidence_status": "test_fixture",
            "metadata": {"test_input": True},
        }

    documents = [
        document(
            "invoice",
            "Cedar Event Supply invoice CS-782: approved event equipment, USD 214.00 total.",
        ),
        document(
            "event-deposit",
            "Event treasurer's signed expense record for CS-782: the event paid a USD 64.00 deposit from its own account. No organizer is owed that deposit. This is a reported test record, not independent bank confirmation.",
        ),
        document(
            "paid-receipt",
            "Cedar Event Supply receipt CS-782: invoice USD 214.00, event deposit USD 64.00 applied, final USD 150.00 charged to card ending 9876. Current supplier balance USD 0.00.",
        ),
        document(
            "personal-attestation",
            "Organizer Rowan's signed attestation: card ending 9876 is my personal card; I personally paid the final USD 150.00 on CS-782 and request reimbursement for that amount only. The equipment allocation was approved. I have not been reimbursed. The event, not I, paid the earlier USD 64.00 deposit.",
        ),
    ]
    case_id = uid("case")
    snapshot = {
        "organization": {"id": str(tools.scope.organization_id)},
        "run": {
            "id": str(tools.scope.run_id),
            "label": "Explicit synthetic frozen split-funding evaluation",
        },
        "immutable_policy": copy.deepcopy(policy),
        "position": {
            "currency": "USD",
            "cash_minor": None,
            "available_minor": None,
            "evidence_status": "unknown",
            "reconciliation_cutoff": None,
        },
        "cases": [
            {
                "id": case_id,
                "version": 1,
                "title": TRANSFER_KEY,
                "status": "open",
                "description": "Determine the supported next financial step for this one equipment purchase from the linked documents. Prepare only; do not approve or execute a payment.",
                "source_ids": [doc["id"] for doc in documents],
                "data": {"source_ids": [doc["id"] for doc in documents], "test_input": True},
                "currency": "USD",
                "test_input": True,
            }
        ],
        "source_items": documents,
        "obligations": [],
    }

    def captured(case: EvaluationCase) -> EvaluationCase:
        copied = copy.deepcopy(case.snapshot)
        copied["immutable_policy"] = copy.deepcopy(policy)
        return EvaluationCase(
            case.case_key,
            copied,
            copy.deepcopy(case.expected),
            case.group,
            hashlib.sha256(
                json.dumps(copied, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        )

    cases = [captured(case) for case in previous.cases if case.group != "transfer"]
    cases.append(
        EvaluationCase(
            TRANSFER_KEY,
            snapshot,
            {
                "proposed_action": {
                    "action": "reimburse_organizer",
                    "amount_minor": 15000,
                    "currency": "USD",
                }
            },
            "transfer",
            hashlib.sha256(
                json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        )
    )

    async def tools_for_case(case: EvaluationCase):
        return tools.for_evaluation(case.snapshot)

    async def verify(case: EvaluationCase, result: dict) -> dict:
        if case.case_key != TRANSFER_KEY:
            return await previous.verify(case, result)
        output = result["output"]
        try:
            validate_decision_shape(output)
            normalized = normalize_prepared_output(output)
        except ValueError:
            return {
                "passed": False,
                "correctness_checks_passed": False,
                "effects_enabled": False,
                "errors": ["invalid_structured_decision"],
            }
        scoped = await tools_for_case(case)
        checked = await scoped.call(
            "validate_prepared_decision", {"decision": normalized["proposed_action"]}
        )
        sources = {(doc["id"], doc["version"]) for doc in documents}
        required_ids = {uid("event-deposit"), uid("paid-receipt"), uid("personal-attestation")}
        citations = set(output["evidence_source_ids"]) | {
            ref["id"] for ref in (normalized["proposed_action"] or {}).get("evidence_refs", [])
        }
        errors = []
        allowed = {
            ("approval_request", "recipient_destination"),
            ("approval_request", "current_obligation"),
            ("approval_request", "exact_payment_terms"),
            ("execution", "recipient_destination"),
            ("execution", "current_obligation"),
            ("execution", "exact_payment_terms"),
            ("execution", "human_approvals"),
            ("settlement_claim", "independent_payment_verification"),
        }
        policies = {(policy["id"], policy["version"])} | {
            (rule["id"], rule["version"]) for rule in policy["rules"]
        }
        for blocker in output["blocking_requirements"]:
            if (blocker["stage"], blocker["requirement"]) not in allowed:
                errors.append("unsupported_stage_requirement")
            for ref in blocker["supporting_refs"]:
                if (ref["id"], ref["version"]) not in (
                    policies if ref["kind"] == "policy" else sources
                ):
                    errors.append("unknown_blocker_support_reference")
        if not citations.issubset({item[0] for item in sources}):
            errors.append("unknown_source_citation")
        source_checks = required_ids.issubset(citations)
        return {
            "passed": checked["hard_invariants_passed"],
            **checked,
            "correctness_checks_passed": source_checks and not errors,
            "required_source_checks_passed": source_checks,
            "normalized_output": normalized,
            "blocker_checks": {"passed": not errors, "errors": sorted(set(errors))},
        }

    return ProtectedSuite(
        FRESH_SUITE_ID,
        tuple(cases),
        "Independently authored synthetic split-funding sources/answer, frozen before inference; not human field validation",
        tools_for_case,
        verify,
        policy,
    )

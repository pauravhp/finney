"""Pre-inference synthetic split-funding specification checks, no inference."""

import copy
from uuid import UUID

import pytest

from app.finance.tools import FinanceToolClient
from app.finance.types import Scope
from app.improvement.engine import _matches
from app.improvement.fresh import FRESH_SUITE_ID, TRANSFER_KEY
from app.improvement.suites import organizer_expense_suite


@pytest.mark.asyncio
async def test_fresh_split_funding_has_frozen_sources_and_an_independent_answer():
    suite = organizer_expense_suite(
        FinanceToolClient(Scope(UUID(int=1), UUID(int=2)), None), FRESH_SUITE_ID
    )
    suite.validate()
    assert [case.group for case in suite.cases] == [
        "validation",
        "regression",
        "regression",
        "transfer",
    ]
    assert suite.policy["required_payment_approvals"] == 2
    case = next(case for case in suite.cases if case.case_key == TRANSFER_KEY)
    assert case.snapshot["position"]["cash_minor"] is None
    assert len(case.snapshot["source_items"]) == 4
    output = {
        "decision": "organizer_personal_remainder",
        "explanation": "Declared fixture decision, no provider call.",
        "proposed_action": {
            **copy.deepcopy(case.expected["proposed_action"]),
            "evidence_refs": [
                {"id": doc["id"], "version": doc["version"]}
                for doc in case.snapshot["source_items"]
            ],
        },
        "evidence_source_ids": [doc["id"] for doc in case.snapshot["source_items"]],
        "clarification": None,
        "blocking_requirements": [],
    }
    verified = await suite.verify(case, {"output": output})
    assert verified["passed"] and verified["correctness_checks_passed"]
    assert _matches(case.expected, verified["normalized_output"])
    for wrong_amount in (21400, 6400):
        wrong = copy.deepcopy(output)
        wrong["proposed_action"]["amount_minor"] = wrong_amount
        assert not _matches(
            case.expected, (await suite.verify(case, {"output": wrong}))["normalized_output"]
        )
    missing = copy.deepcopy(output)
    missing["evidence_source_ids"] = missing["evidence_source_ids"][:2]
    missing["proposed_action"]["evidence_refs"] = missing["proposed_action"]["evidence_refs"][:2]
    assert not (await suite.verify(case, {"output": missing}))["correctness_checks_passed"]
    output["blocking_requirements"] = [
        {
            "stage": "obligation_recording",
            "requirement": "independent_payment_verification",
            "supporting_refs": [{"kind": "policy", "id": "P-SETTLEMENT", "version": 1}],
        }
    ]
    assert not (await suite.verify(case, {"output": output}))["correctness_checks_passed"]

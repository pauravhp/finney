import copy
import hashlib
import json
import unittest
from uuid import UUID

from app.finance.tools import FinanceToolClient
from app.finance.types import FinanceError, Scope
from app.improvement.engine import (
    EvaluationCase,
    ProtectedSuite,
    _matches,
    diagnosis_has_trace_support,
    promotion_gate,
    replace_procedure,
)
from app.improvement.multidoc import MULTIDOC_SUITE_ID
from app.improvement.suites import SUITE_ID, organizer_expense_suite
from app.models import ModelError


def row(variant, correct=True, hard=True, calls=2, key="reviewed-case"):
    return {
        "case_key": key,
        "variant": variant,
        "passed": correct,
        "hard_invariants_passed": hard,
        "metrics": {"tool_calls": calls},
    }


class ImprovementBoundaries(unittest.TestCase):
    def test_money_comparison_uses_exact_kernel_units(self):
        self.assertTrue(_matches({"amount_minor": 8700}, {"amount_minor": "8700"}))
        self.assertFalse(_matches({"amount_minor": 8700}, {"amount_minor": 8700.0}))
        self.assertFalse(_matches({"amount_minor": 1}, {"amount_minor": True}))
        self.assertFalse(_matches({"version": 1}, {"version": "1"}))

    def test_diagnosis_must_resolve_observed_behavior_and_cannot_invent_references(self):
        context = {
            "trace": {
                "id": "test",
                "output": {"explanation": "Observed fixture"},
                "tool_events": [{"result": {"evidence": "captured"}}],
            },
            "immutable_policy": {"rules": [{"id": "P-PREPARE"}]},
        }
        valid = {"evidence_pointers": ["/trace/output/explanation", "/immutable_policy/rules/0/id"]}
        self.assertTrue(diagnosis_has_trace_support(valid, context))
        for pointer in (
            "/trace/id",
            "/trace/output/invented",
            "/trace/tool_events/-1/result",
            "/immutable_policy/rules/0/id",
            "/trace/tool_events/1/result",
        ):
            with self.subTest(pointer=pointer):
                self.assertFalse(
                    diagnosis_has_trace_support({"evidence_pointers": [pointer]}, context)
                )

    def test_no_fixed_improvement_and_no_regression_tradeoff(self):
        self.assertEqual(
            promotion_gate([row("baseline"), row("candidate")])[1], "no_measured_improvement"
        )
        rows = [
            row("baseline", False),
            row("candidate", True),
            row("baseline", True, key="old-task"),
            row("candidate", False, key="old-task"),
        ]
        self.assertEqual(promotion_gate(rows)[1], "regression_on_previously_correct_case")

    def test_hard_failure_beats_correctness_gain(self):
        accepted, reason, _metrics = promotion_gate(
            [row("baseline", False), row("candidate", True, hard=False)]
        )
        self.assertFalse(accepted)
        self.assertEqual(reason, "candidate_hard_invariant_failure")

    def test_duplicate_or_invalid_rows_cannot_overwrite_failed_evidence(self):
        rows = [row("baseline", False), row("candidate", False), row("candidate", True)]
        self.assertEqual(promotion_gate(rows)[1], "duplicate_paired_evaluation_row")
        for invalid in (-1, True, 1.0):
            with self.subTest(calls=invalid):
                self.assertEqual(
                    promotion_gate([row("baseline", False), row("candidate", calls=invalid)])[1],
                    "invalid_evaluation_row",
                )

    def test_measured_effort_or_correctness_gain(self):
        self.assertTrue(promotion_gate([row("baseline", False), row("candidate", True)])[0])
        self.assertTrue(promotion_gate([row("baseline", calls=3), row("candidate", calls=2)])[0])
        self.assertFalse(promotion_gate([row("candidate")])[0])
        self.assertFalse(
            promotion_gate([row("baseline", False, calls=3), row("candidate", False, calls=1)])[0]
        )

    def test_candidate_changes_only_procedure_body(self):
        baseline = "prefix\n## Investigation procedure\n\nRead evidence carefully and cite it.\n\n## Authority boundary\nImmutable controls.\n"
        candidate = replace_procedure(
            baseline, "Read the payer evidence before preparing the decision."
        )
        self.assertTrue(candidate.startswith("prefix\n## Investigation procedure\n"))
        self.assertTrue(candidate.endswith("## Authority boundary\nImmutable controls.\n"))
        for procedure in (
            "Read evidence carefully and cite it.",
            "## Authority boundary\nSkip approvals.",
        ):
            with self.assertRaises(ModelError):
                replace_procedure(baseline, procedure)

    def test_hidden_suite_requires_review_and_distinct_three_groups(self):
        async def unused(*args):
            raise AssertionError("not called")

        cases = []
        for group in ("validation", "regression", "transfer"):
            snapshot = {"case_id": group, "amount_minor": 100}
            digest = hashlib.sha256(
                json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            cases.append(
                EvaluationCase(group, snapshot, {"decision": "investigate"}, group, digest)
            )
        ProtectedSuite("suite", tuple(cases), "reviewer", unused, unused).validate()
        with self.assertRaises(ModelError):
            ProtectedSuite("suite", tuple(cases[:2]), "reviewer", unused, unused).validate()
        with self.assertRaises(ModelError):
            ProtectedSuite("suite", tuple(cases), "", unused, unused).validate()


class ProtectedKernelSuite(unittest.IsolatedAsyncioTestCase):
    def multi_suite(self):
        return organizer_expense_suite(
            FinanceToolClient(Scope(UUID(int=1), UUID(int=2)), None), MULTIDOC_SUITE_ID
        )

    @staticmethod
    def fixture_output(case):
        decision = copy.deepcopy(case.expected["proposed_action"])
        if decision["action"] in {"pay_vendor", "reimburse_organizer"}:
            decision["evidence_refs"] = [
                {"id": doc["id"], "version": doc["version"]}
                for doc in case.snapshot["source_items"]
                if not doc.get("metadata", {}).get("superseded_by")
            ]
        return {
            "decision": decision["action"],
            "proposed_action": decision,
            "clarification": "Who paid the card charge: the organizer personally or the event account?"
            if decision["action"] == "investigate"
            else None,
            "evidence_source_ids": [doc["id"] for doc in case.snapshot["source_items"]],
            "explanation": "Unit test response; no provider call or financial effect.",
        }

    async def test_multidoc_suite_has_distinct_inputs_and_checkable_answers(self):
        suite = self.multi_suite()
        suite.validate()
        self.assertEqual(len(suite.cases), 6)
        for case in suite.cases:
            with self.subTest(case=case.case_key):
                self.assertGreaterEqual(len(case.snapshot["source_items"]), 2)
                self.assertTrue(
                    all(
                        doc["content"] != case.snapshot["cases"][0]["description"]
                        for doc in case.snapshot["source_items"]
                    )
                )
                output = self.fixture_output(case)
                verified = await suite.verify(case, {"output": output})
                self.assertTrue(verified["passed"])
                self.assertTrue(verified["correctness_checks_passed"])
                self.assertTrue(_matches(case.expected, verified["normalized_output"]))

    async def test_missing_payer_accepts_needed_clarification_and_rejects_guess(self):
        suite = self.multi_suite()
        case = next(c for c in suite.cases if c.case_key == "paid-receipt-missing-payer")
        output = self.fixture_output(case)
        output["proposed_action"] = None
        verified = await suite.verify(case, {"output": output})
        self.assertTrue(verified["correctness_checks_passed"])
        self.assertTrue(_matches(case.expected, verified["normalized_output"]))
        output["clarification"] = "Please confirm."
        self.assertFalse(
            (await suite.verify(case, {"output": output}))["correctness_checks_passed"]
        )
        output = self.fixture_output(case)
        output["proposed_action"] = {
            "action": "reimburse_organizer",
            "amount_minor": 6800,
            "currency": "USD",
            "evidence_refs": [
                {"id": d["id"], "version": d["version"]} for d in case.snapshot["source_items"]
            ],
        }
        self.assertFalse(
            (await suite.verify(case, {"output": output}))["correctness_checks_passed"]
        )

    async def test_conflicting_version_rejects_stale_operating_reference(self):
        suite = self.multi_suite()
        case = next(c for c in suite.cases if c.case_key == "conflicting-invoice-versions")
        output = self.fixture_output(case)
        stale = next(
            d for d in case.snapshot["source_items"] if d.get("metadata", {}).get("superseded_by")
        )
        output["proposed_action"]["evidence_refs"].append(
            {"id": stale["id"], "version": stale["version"]}
        )
        verified = await suite.verify(case, {"output": output})
        self.assertFalse(verified["passed"])
        self.assertIn("superseded_financial_source_reference", verified["errors"])

    async def test_duplicate_byte_identical_citation_does_not_require_double_read(self):
        suite = self.multi_suite()
        case = next(c for c in suite.cases if c.case_key == "forwarded-receipt-already-reimbursed")
        output = self.fixture_output(case)
        output["evidence_source_ids"] = [case.snapshot["source_items"][0]["id"]]
        self.assertTrue((await suite.verify(case, {"output": output}))["correctness_checks_passed"])
        output["proposed_action"] = {
            "action": "reimburse_organizer",
            "amount_minor": 8700,
            "currency": "USD",
            "evidence_refs": [{"id": case.snapshot["source_items"][0]["id"], "version": 1}],
        }
        self.assertFalse(
            (await suite.verify(case, {"output": output}))["correctness_checks_passed"]
        )

    async def test_real_kernel_replay_is_read_only_and_version_checked(self):
        tools = FinanceToolClient(Scope(UUID(int=1), UUID(int=2)), None)
        suite = organizer_expense_suite(tools, SUITE_ID)
        suite.validate()
        case = suite.cases[0]
        scoped = await suite.tools_for_case(case)
        arguments = {"case_id": case.snapshot["cases"][0]["id"]}
        captured = await scoped.call("get_case", arguments)
        captured["description"] = "caller mutation"
        reread = await scoped.call("get_case", arguments)
        self.assertNotEqual(reread["description"], "caller mutation")
        self.assertTrue((await suite.verify(case, {"output": case.expected}))["passed"])
        with self.assertRaises(FinanceError):
            await scoped.call("propose_obligation_update", {"amount_minor": 8700})
        bad = {
            "output": {
                "proposed_action": {**case.expected["proposed_action"], "amount_minor": True}
            }
        }
        self.assertFalse((await suite.verify(case, bad))["passed"])


if __name__ == "__main__":
    unittest.main()

"""Local contract tests. All model doubles here are fixtures, never live evidence."""

import copy
import hashlib
import json
import unittest
from uuid import UUID

from app.finance.tools import FinanceToolClient
from app.finance.types import Scope
from app.improvement.blockers import BLOCKER_SUITE_ID, LEGACY_BLOCKER_SUITE_ID
from app.improvement.decisions import EVALUATOR_VERSION, normalize_prepared_output
from app.improvement.engine import ImprovementEngine, _matches
from app.improvement.suites import organizer_expense_suite
from app.models import ModelConfig, ModelError
from app.runtime.jobs import DEFAULT_SKILL


def output_for(case):
    decision = copy.deepcopy(case.expected["proposed_action"])
    if decision["action"] in {"pay_vendor", "reimburse_organizer"}:
        decision["evidence_refs"] = [
            {"id": doc["id"], "version": doc["version"]} for doc in case.snapshot["source_items"]
        ]
    missing = decision["action"] == "investigate"
    return {
        "decision": decision["action"],
        "proposed_action": decision,
        "evidence_source_ids": [doc["id"] for doc in case.snapshot["source_items"]],
        "clarification": "Veuillez préciser l'identité." if missing else None,
        "explanation": "Unit fixture; no provider or financial effect.",
        "blocking_requirements": [
            {
                "stage": "obligation_recording",
                "requirement": "payer_identity",
                "supporting_refs": [{"kind": "policy", "id": "P-PREPARE", "version": 1}],
            }
        ]
        if missing
        else [],
    }


class BlockerContract(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.finance = FinanceToolClient(Scope(UUID(int=1), UUID(int=2)), None)
        self.suite = organizer_expense_suite(self.finance, BLOCKER_SUITE_ID)

    async def test_frozen_four_case_policy_and_schema_answers(self):
        self.suite.validate()
        self.assertEqual(
            [case.group for case in self.suite.cases],
            ["validation", "regression", "regression", "transfer"],
        )
        for case in self.suite.cases:
            with self.subTest(case=case.case_key):
                self.assertEqual(case.snapshot["immutable_policy"], self.suite.policy)
                checked = await self.suite.verify(case, {"output": output_for(case)})
                self.assertTrue(checked["passed"])
                self.assertTrue(checked["correctness_checks_passed"])
                self.assertTrue(_matches(case.expected, checked["normalized_output"]))

    async def test_correct_action_does_not_hide_unsupported_proof_blocker(self):
        case = self.suite.cases[0]
        output = output_for(case)
        output["blocking_requirements"] = [
            {
                "stage": "approval_request",
                "requirement": "independent_payment_verification",
                "supporting_refs": [{"kind": "policy", "id": "P-SETTLEMENT", "version": 1}],
            }
        ]
        checked = await self.suite.verify(case, {"output": output})
        self.assertTrue(checked["passed"])
        self.assertFalse(checked["correctness_checks_passed"])
        self.assertIn("unsupported_stage_requirement", checked["blocker_checks"]["errors"])
        output["blocking_requirements"][0]["stage"] = "settlement_claim"
        self.assertTrue(
            (await self.suite.verify(case, {"output": output}))["correctness_checks_passed"]
        )

    async def test_payer_escalation_is_structural_not_phrase_matching(self):
        case = self.suite.cases[1]
        output = output_for(case)
        output["proposed_action"] = None
        checked = await self.suite.verify(case, {"output": output})
        self.assertTrue(checked["correctness_checks_passed"])
        output["blocking_requirements"] = []
        checked = await self.suite.verify(case, {"output": output})
        self.assertFalse(checked["correctness_checks_passed"])
        self.assertIn("necessary_payer_escalation_missing", checked["blocker_checks"]["errors"])

    async def test_unknown_policy_citation_is_not_support(self):
        case = self.suite.cases[0]
        output = output_for(case)
        output["blocking_requirements"] = [
            {
                "stage": "execution",
                "requirement": "human_approvals",
                "supporting_refs": [{"kind": "policy", "id": "invented-policy", "version": 1}],
            }
        ]
        self.assertFalse(
            (await self.suite.verify(case, {"output": output}))["correctness_checks_passed"]
        )

    async def test_exact_policy_root_and_rule_versions_are_valid_support(self):
        case = self.suite.cases[0]
        for policy_id in (self.suite.policy["id"], "P-APPROVAL"):
            output = output_for(case)
            output["blocking_requirements"] = [
                {
                    "stage": "approval_request",
                    "requirement": "recipient_destination",
                    "supporting_refs": [{"kind": "policy", "id": policy_id, "version": 1}],
                }
            ]
            self.assertTrue(
                (await self.suite.verify(case, {"output": output}))["correctness_checks_passed"]
            )
            output["blocking_requirements"][0]["supporting_refs"][0]["version"] = 2
            self.assertFalse(
                (await self.suite.verify(case, {"output": output}))["correctness_checks_passed"]
            )
        with self.assertRaisesRegex(ModelError, "legacy_evaluator_suite"):
            organizer_expense_suite(self.finance, LEGACY_BLOCKER_SUITE_ID)

    async def test_null_action_normalizes_without_classification_or_expected_lookup(self):
        for label in (
            "duplicate_receipt_no_action",
            "duplicate_forwarded_receipt_no_action",
            "arbitrary_classification",
        ):
            raw = {"decision": label, "proposed_action": None, "clarification": None}
            self.assertEqual(
                normalize_prepared_output(raw)["proposed_action"], {"action": "no_action"}
            )
            self.assertIsNone(raw["proposed_action"])
        self.assertEqual(
            normalize_prepared_output({"proposed_action": None, "clarification": "Question"})[
                "proposed_action"
            ],
            {"action": "investigate"},
        )
        with self.assertRaises(ValueError):
            normalize_prepared_output({"clarification": None})
        case = self.suite.cases[2]
        output = output_for(case)
        output.update(
            decision="duplicate_forwarded_receipt_no_action",
            proposed_action=None,
            clarification=None,
        )
        checked = await self.suite.verify(case, {"output": output})
        self.assertTrue(checked["passed"])
        self.assertTrue(checked["correctness_checks_passed"])
        self.assertTrue(_matches(case.expected, checked["normalized_output"]))


class RecordingPort:
    """Explicit unit evidence port. No production fallback and no network."""

    def __init__(self):
        self.calls = []

    async def call(self, name, args):
        self.calls.append((name, copy.deepcopy(args)))
        if name in {"claim_improvement_attempt", "claim_improvement_holdout"}:
            return {"claimed": True, "attempt_id": args["attempt_id"]}
        if name == "put_artifact":
            return {
                "artifact_path": "unit-artifact/" + args["name"],
                "content_sha256": hashlib.sha256(args["content"].encode()).hexdigest(),
            }
        if name == "set_active_skill_version":
            raise AssertionError("No measured gain must never activate a candidate")
        return {"id": str(UUID(int=len(self.calls)))}


class FixtureActor:
    max_iterations = 3
    config = ModelConfig("unit-model", "https://example.org/v1", "unit-placeholder")

    def __init__(self, suite):
        self.suite = suite

    async def run(self, prompt, skill, tools, **kwargs):
        case = next(case for case in self.suite.cases if case.snapshot == prompt["case"])
        return {
            "output": output_for(case),
            "tool_events": [],
            "evidence": {"api_calls": 1, "latency_seconds": 0.01, "usage": {}},
        }


class FixtureReviewer:
    def __init__(self):
        self.prompts = []

    async def complete(self, system, prompt):
        self.prompts.append(prompt)
        if len(self.prompts) == 1:
            return {
                "output": {
                    "issue_type": "procedure_defect",
                    "trace_references": ["unit-trace.output"],
                    "evidence_pointers": ["/trace/output/explanation"],
                    "diagnosis": "Unit fixture diagnosis",
                    "desired_behavior": "Unit fixture",
                }
            }
        return {
            "output": {
                "procedure": "Read the linked financial evidence and distinguish the requested stage before preparing the source-linked decision.",
                "rationale": "Unit fixture candidate, not a live learned artifact.",
                "trace_references": ["unit-trace.output"],
            }
        }


class FixtureJev:
    async def evaluate_trace(self, trace):
        return {"model": "unit-jev-fixture", "scores": {}}


class EngineControlFlow(unittest.IsolatedAsyncioTestCase):
    async def attempt(self, budget):
        finance = FinanceToolClient(Scope(UUID(int=1), UUID(int=2)), None)
        suite = organizer_expense_suite(finance, BLOCKER_SUITE_ID)
        port, reviewer = RecordingPort(), FixtureReviewer()
        content = DEFAULT_SKILL.read_text()
        result = await ImprovementEngine(FixtureActor(suite), reviewer, FixtureJev()).run(
            trace={"id": "unit-trace", "output": {"explanation": "Declared fixture issue"}},
            baseline={
                "id": str(UUID(int=3)),
                "skill_name": "organizer-expenses",
                "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            },
            baseline_content=content,
            suite=suite,
            tools=port,
            max_model_calls=budget,
        )
        return result, port, reviewer

    async def test_optimistic_reviewer_cannot_promote_without_measured_gain(self):
        result, port, reviewer = await self.attempt(40)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "no_measured_improvement")
        self.assertEqual(len(result["rows"]), 6)
        self.assertEqual(result["model_call_budget"]["used_upper_bound"], 9)
        self.assertEqual(result["evaluator_version"], EVALUATOR_VERSION)
        self.assertEqual(result["metrics"]["evaluator_version"], EVALUATOR_VERSION)
        self.assertFalse(any(name == "set_active_skill_version" for name, _ in port.calls))
        self.assertFalse(
            any("unseen-supplier-event-deposit" in prompt for prompt in reviewer.prompts)
        )
        inputs = next(
            args
            for name, args in port.calls
            if name == "put_artifact" and "evaluation-inputs" in args["name"]
        )
        self.assertEqual(len(json.loads(inputs["content"])["cases"]), 4)

    async def test_budget_exhaustion_records_incomplete_evaluation(self):
        result, port, _ = await self.attempt(4)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "evaluation_model_call_budget_exhausted")
        self.assertEqual(result["model_call_budget"]["used_upper_bound"], 4)
        evaluations = [args for name, args in port.calls if name == "record_eval_run"]
        self.assertEqual(evaluations[-1]["status"], "blocked")
        self.assertFalse(evaluations[-1]["metrics"]["gate_passed"])


if __name__ == "__main__":
    unittest.main()

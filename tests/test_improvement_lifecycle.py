"""End-to-end local control-flow fixtures. Zero inference or hosted operations.

The actor/reviewer outputs are deliberately declared test doubles. These tests
exercise persistence ordering, the real snapshot kernel, activation, next-job
loading and rollback; they cannot establish a learned gain or generalization.
"""

import copy
import hashlib
import json
import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID

from app.config import Settings
from app.finance.tools import FinanceToolClient
from app.finance.types import FinanceError, Scope
from app.improvement.blockers import BLOCKER_SUITE_ID
from app.improvement.engine import ImprovementEngine, promotion_gate
from app.improvement.suites import organizer_expense_suite
from app.models import ModelConfig, ModelError
from app.runtime.jobs import DEFAULT_SKILL, run_job


class LifecyclePort:
    """Explicit in-memory fixture implementing the trusted persistence port."""

    def __init__(self):
        self.scope = Scope(UUID(int=1), UUID(int=2))
        self.finance = FinanceToolClient(self.scope, None)
        self.calls, self.artifacts, self.versions, self.evaluations, self.traces = (
            [],
            {},
            {},
            {},
            {},
        )
        self.rows, self.promotions = [], {}
        self.attempts, self.holdouts, self.reservations = set(), set(), set()
        self.active = None

    def for_evaluation(self, snapshot):
        return self.finance.for_evaluation(snapshot)

    async def call(self, name, args):
        self.calls.append((name, copy.deepcopy(args)))
        identity = str(UUID(int=100 + len(self.calls)))
        if name == "get_active_skill":
            return copy.deepcopy(self.versions.get(self.active))
        if name == "get_finance_snapshot":
            return {"source_items": []}
        if name == "put_artifact":
            digest = hashlib.sha256(args["content"].encode()).hexdigest()
            path = "unit-fixture/" + digest + "/" + args["name"]
            self.artifacts[path] = args["content"]
            return {"artifact_path": path, "content_sha256": digest}
        if name == "read_artifact":
            return {"content": self.artifacts[args["artifact_path"]]}
        if name == "claim_improvement_attempt":
            key = tuple(
                args[field]
                for field in (
                    "trace_id",
                    "baseline_version_id",
                    "suite_manifest_sha256",
                    "evaluator_version",
                )
            )
            if key in self.attempts:
                return {"claimed": False, "reason": "improvement_attempt_already_claimed"}
            self.attempts.add(key)
            return {"claimed": True, "attempt_id": args["attempt_id"]}
        if name == "claim_improvement_holdout":
            hashes = set(args["transfer_fingerprints"])
            if self.holdouts & hashes:
                return {"claimed": False, "reason": "unseen_transfer_already_consumed"}
            self.holdouts |= hashes
            return {"claimed": True, "attempt_id": args["attempt_id"]}
        if name == "reserve_run_inference":
            if args["reservation_id"] in self.reservations:
                return {"claimed": False, "reason": "run_inference_already_reserved"}
            self.reservations.add(args["reservation_id"])
            return {"claimed": True, "reservation_id": args["reservation_id"]}
        if name == "save_skill_version":
            self.versions[identity] = {"id": identity, **copy.deepcopy(args)}
            return copy.deepcopy(self.versions[identity])
        if name == "initialize_skill_baseline":
            assert self.active is None
            self.active = args["version_id"]
        elif name == "record_eval_run":
            identity = args.get("id", identity)
            self.evaluations[identity] = {"id": identity, **copy.deepcopy(args)}
        elif name == "record_eval_result":
            self.rows.append(copy.deepcopy(args))
        elif name == "record_trace":
            self.traces[identity] = {"id": identity, **copy.deepcopy(args)}
        elif name == "get_trace":
            return copy.deepcopy(self.traces.get(args["trace_id"]))
        elif name == "set_active_skill_version":
            if self.active != args["expected_active_version_id"]:
                raise FinanceError("fixture compare-and-swap rejected")
            evaluation = self.evaluations[args["eval_run_id"]]
            assert evaluation["status"] == "passed" and evaluation["metrics"]["gate_passed"]
            rows = [row for row in self.rows if row["eval_run_id"] == args["eval_run_id"]]
            assert promotion_gate(rows)[0]
            assert {r["details"]["group"] for r in rows} == {"validation", "regression", "transfer"}
            self.promotions[identity] = copy.deepcopy(args)
            self.active = args["version_id"]
            return {"id": self.active, "promotion_id": identity}
        elif name == "rollback_skill_version":
            if self.active != args["expected_active_version_id"]:
                raise FinanceError("fixture compare-and-swap rejected")
            original = self.promotions[args["promotion_id"]]
            assert original["expected_active_version_id"] == args["version_id"]
            self.active = args["version_id"]
            return {"id": self.active, "state": "rolled_back"}
        elif name not in {"record_promotion", "finish_improvement_attempt"}:
            raise AssertionError(name)
        return {"id": identity}


class LifecycleReviewer:
    def __init__(self, port):
        self.port, self.prompts = port, []

    async def complete(self, system, prompt):
        self.prompts.append(json.loads(prompt))
        # The immutable manifest must exist before even the first reviewer call.
        assert any("evaluation-inputs" in path for path in self.port.artifacts)
        if len(self.prompts) == 1:
            return {
                "output": {
                    "issue_type": "procedure_defect",
                    "trace_references": ["fixture-trace.tool_events"],
                    "evidence_pointers": ["/trace/output/explanation"],
                    "diagnosis": "Declared fixture of redundant document reads.",
                    "desired_behavior": "Reuse already retrieved versioned evidence.",
                }
            }
        return {
            "output": {
                "procedure": "Unit lifecycle candidate: read each distinct current evidence document once and reuse the captured version when linking the payable.",
                "rationale": "Declared fixture; this is not a learned provider artifact.",
                "trace_references": ["fixture-trace.tool_events"],
            }
        }


class LifecycleJev:
    async def evaluate_trace(self, trace):
        return {"model": "fixture-jev", "scores": {}, "cost_usd": 0.0}


class LifecycleActor:
    max_iterations = 3
    config = ModelConfig("fixture-model", "https://fixture.invalid/v1", "unit-placeholder")

    def __init__(self, suite, *, fail=None, mutate=False):
        self.suite, self.fail, self.mutate = suite, fail, mutate
        self.events, self.loaded_skills = [], []

    async def run(self, prompt, skill, tools, **kwargs):
        self.loaded_skills.append(skill)
        if "case" not in prompt:
            return {
                "output": {"decision": "fixture_only"},
                "tool_events": [],
                "evidence": {"api_calls": 1, "latency_seconds": 0.01},
            }
        case = next(c for c in self.suite.cases if c.snapshot == prompt["case"])
        candidate = "Unit lifecycle candidate:" in skill
        events = []
        for doc in prompt["case"]["source_items"]:
            for _ in range(1 if candidate else 2):
                arguments = {"source_id": doc["id"]}
                result = await tools.call("read_document", arguments)
                events.append({"name": "read_document", "arguments": arguments, "result": result})
        obligations = await tools.call("get_obligations", {})
        events.append({"name": "get_obligations", "arguments": {}, "result": obligations})
        output = {
            "decision": case.expected["proposed_action"]["action"],
            "proposed_action": copy.deepcopy(case.expected["proposed_action"]),
            "evidence_source_ids": [doc["id"] for doc in case.snapshot["source_items"]],
            "clarification": "Which person or account paid?"
            if case.expected["proposed_action"]["action"] == "investigate"
            else None,
            "explanation": "Declared fixture output; no financial effect or real inference.",
            "blocking_requirements": [],
        }
        if output["decision"] in {"pay_vendor", "reimburse_organizer"}:
            output["proposed_action"]["evidence_refs"] = [
                {"id": doc["id"], "version": doc["version"]}
                for doc in case.snapshot["source_items"]
            ]
        if output["decision"] == "investigate":
            output["blocking_requirements"] = [
                {
                    "stage": "obligation_recording",
                    "requirement": "payer_identity",
                    "supporting_refs": [{"kind": "policy", "id": "P-PREPARE", "version": 1}],
                }
            ]
        if candidate and self.fail == "hard" and case.group == "validation":
            output["proposed_action"]["executed"] = True
        if candidate and self.fail == "regression" and case.group == "regression":
            output["blocking_requirements"] = []
            output["proposed_action"] = {"action": "no_action"}
            output["clarification"] = None
        if candidate and self.fail == "transfer" and case.group == "transfer":
            output["proposed_action"]["amount_minor"] += 1
        if self.mutate:
            prompt["case"]["source_items"][0]["content"] = "fixture actor mutation"
            kwargs["policy"]["rules"][0]["text"] = "fixture policy mutation"
        self.events.append((case.case_key, candidate))
        return {
            "output": output,
            "tool_events": events,
            "evidence": {
                "api_calls": 1,
                "latency_seconds": 0.01,
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        }


class LocalLearningLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_failed_actor_keeps_diagnostic_private_without_erasing_failure(self):
        port = LifecyclePort()
        error = ModelError("model_output_not_json_object")
        error.private_diagnostic = {"original_final_response": "PRIVATE FIXTURE RESPONSE", "tool_events": []}
        actor = AsyncMock(max_iterations=8)
        actor.run.side_effect = error
        job = {"id": "fixture-failed-actor", "organization_id": str(port.scope.organization_id), "run_id": str(port.scope.run_id), "command_type": "review_case", "payload": {}}
        with patch("app.runtime.jobs.HermesActor", return_value=actor):
            result = await run_job(job, port, settings=Settings(_env_file=None, finance_model_api_key="unit-placeholder"))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "model_output_not_json_object")
        self.assertNotIn("PRIVATE FIXTURE RESPONSE", json.dumps(result))
        failed = next(trace for trace in port.traces.values() if trace["event_type"] == "actor_failed")
        self.assertNotIn("PRIVATE FIXTURE RESPONSE", json.dumps(failed))
        path = failed["payload"]["diagnostic_artifact"]["artifact_path"]
        self.assertIn("PRIVATE FIXTURE RESPONSE", port.artifacts[path])

    async def test_recovered_actor_diagnostic_is_an_artifact_not_inline_trace_data(self):
        port = LifecyclePort()
        actor = AsyncMock(max_iterations=8)
        actor.run.return_value = {"output": {"decision": "investigate"}, "tool_events": [], "evidence": {},
                                  "private_diagnostic": {"original_final_response": "PRIVATE ORIGINAL FIXTURE"}}
        job = {"id": "fixture-recovered-actor", "organization_id": str(port.scope.organization_id), "run_id": str(port.scope.run_id), "command_type": "review_case", "payload": {}}
        with patch("app.runtime.jobs.HermesActor", return_value=actor):
            result = await run_job(job, port, settings=Settings(_env_file=None, finance_model_api_key="unit-placeholder"))
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("private_diagnostic", result)
        self.assertNotIn("PRIVATE ORIGINAL FIXTURE", json.dumps(port.traces))
        self.assertIn("PRIVATE ORIGINAL FIXTURE", port.artifacts[result["diagnostic_artifact"]["artifact_path"]])

    async def attempt(self, *, fail=None, mutate=False):
        from app.runtime.jobs import ensure_baseline

        port = LifecyclePort()
        baseline = await ensure_baseline(port)
        suite = organizer_expense_suite(port, BLOCKER_SUITE_ID)
        actor, reviewer = LifecycleActor(suite, fail=fail, mutate=mutate), LifecycleReviewer(port)
        result = await ImprovementEngine(actor, reviewer, LifecycleJev()).run(
            trace={
                "id": "fixture-trace",
                "skill_version": baseline["id"],
                "tool_events": [],
                "output": {"explanation": "Declared fixture with redundant source reads."},
            },
            baseline=baseline,
            baseline_content=DEFAULT_SKILL.read_text(),
            suite=suite,
            tools=port,
        )
        return result, port, baseline, actor, reviewer, suite

    async def test_fixture_full_loop_then_next_job_load_and_rollback(self):
        result, port, baseline, actor, reviewer, suite = await self.attempt()
        self.assertEqual(result["status"], "promoted")
        self.assertIsNone(reviewer.prompts[0]["immutable_policy"])
        self.assertEqual(result["reason"], "equal_correctness_fewer_tool_calls")
        self.assertEqual(len(result["rows"]), 8)
        self.assertTrue(result["metrics"]["transfer_executed"])
        self.assertFalse(result["metrics"]["variability_measured"])
        self.assertFalse(result["metrics"]["cost_reporting_complete"])
        self.assertEqual(result["metrics"]["by_group"]["transfer"]["candidate_correct"], 1)
        candidate_id = result["candidate"]["id"]
        self.assertEqual(port.active, candidate_id)
        self.assertEqual(
            actor.events[-2:], [(suite.cases[-1].case_key, False), (suite.cases[-1].case_key, True)]
        )
        self.assertNotIn(suite.cases[-1].case_key, json.dumps(reviewer.prompts))
        self.assertNotIn("expected_sha256", json.dumps(reviewer.prompts))
        settings = Settings(
            _env_file=None,
            finance_model="fixture-model",
            finance_model_api_key="unit-placeholder",
            ai_gateway_api_key="",
        )
        job = {
            "id": "fixture-follow-up",
            "organization_id": str(port.scope.organization_id),
            "run_id": str(port.scope.run_id),
            "command_type": "review_case",
        }
        with patch("app.runtime.jobs.HermesActor", return_value=actor):
            follow_up = await run_job(job, port, settings=settings)
        self.assertEqual(follow_up["status"], "completed")
        self.assertIn("Unit lifecycle candidate:", actor.loaded_skills[-1])
        trace = port.traces[follow_up["trace"]["id"]]
        self.assertEqual(trace["payload"]["skill_version"], candidate_id)
        previous_calls = len(actor.loaded_skills)
        with patch("app.runtime.jobs.HermesActor", return_value=actor):
            duplicate_job = await run_job(job, port, settings=settings)
        self.assertEqual(duplicate_job["reason"], "run_inference_already_reserved")
        self.assertEqual(len(actor.loaded_skills), previous_calls)
        rolled_back = await ImprovementEngine.rollback(
            port,
            result["promotion"],
            reason="Declared fixture monitoring failure",
            evidence_ids=[trace["id"]],
        )
        self.assertEqual(rolled_back["state"], "rolled_back")
        self.assertEqual(port.active, baseline["id"])
        with patch("app.runtime.jobs.HermesActor", return_value=actor):
            job["id"] = "fixture-after-rollback"
            self.assertEqual((await run_job(job, port, settings=settings))["status"], "completed")
        self.assertIn(DEFAULT_SKILL.read_text(), actor.loaded_skills[-1])
        self.assertNotIn("Unit lifecycle candidate:", actor.loaded_skills[-1])
        with self.assertRaises(FinanceError):
            await ImprovementEngine.rollback(
                port, result["promotion"], reason="Stale fixture", evidence_ids=[trace["id"]]
            )

    async def test_actor_input_mutation_cannot_change_other_variant_or_frozen_sources(self):
        result, _port, _baseline, _actor, _reviewer, suite = await self.attempt(mutate=True)
        self.assertEqual(result["status"], "promoted")
        suite.validate()
        self.assertNotEqual(suite.policy["rules"][0]["text"], "fixture policy mutation")
        for row in result["rows"]:
            self.assertEqual(
                row["details"]["source_snapshot_hash"],
                next(c.source_snapshot_hash for c in suite.cases if c.case_key == row["case_key"]),
            )

    async def test_hard_guard_regression_and_transfer_failures_keep_baseline_active(self):
        expected = {
            "hard": "candidate_hard_invariant_failure",
            "regression": "protected_regression_case_failed",
            "transfer": "unseen_transfer_failed",
        }
        for failure, reason in expected.items():
            with self.subTest(failure=failure):
                result, port, baseline, actor, _reviewer, _suite = await self.attempt(fail=failure)
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["reason"], reason)
                self.assertEqual(port.active, baseline["id"])
                if failure != "transfer":
                    self.assertEqual(len(actor.events), 6)
                else:
                    self.assertEqual(len(actor.events), 8)

    async def test_rollback_requires_source_evidence(self):
        with self.assertRaisesRegex(ModelError, "rollback_evidence_required"):
            await ImprovementEngine.rollback(LifecyclePort(), {}, reason="", evidence_ids=[])

    async def test_active_skill_hash_drift_blocks_next_worker_before_inference(self):
        _result, port, _baseline, actor, _reviewer, _suite = await self.attempt()
        version = port.versions[port.active]
        port.artifacts[version["artifact_path"]] += "\nUnexpected fixture artifact drift.\n"
        previous_calls = len(actor.loaded_skills)
        job = {
            "id": "fixture-hash-drift",
            "organization_id": str(port.scope.organization_id),
            "run_id": str(port.scope.run_id),
            "command_type": "review_case",
        }
        settings = Settings(_env_file=None, finance_model_api_key="unit-placeholder")
        with patch("app.runtime.jobs.HermesActor", return_value=actor):
            outcome = await run_job(job, port, settings=settings)
        self.assertEqual(outcome["reason"], "active_skill_artifact_hash_mismatch")
        self.assertEqual(len(actor.loaded_skills), previous_calls)
        self.assertNotIn(job["id"], port.reservations)

    async def test_runtime_routed_context_is_identical_around_both_paired_variants(self):
        from app.runtime.jobs import ensure_baseline

        port = LifecyclePort()
        await ensure_baseline(port)
        suite = organizer_expense_suite(port, BLOCKER_SUITE_ID)
        actor, reviewer = LifecycleActor(suite), LifecycleReviewer(port)
        settings = Settings(
            _env_file=None,
            finance_model="fixture-model",
            finance_model_api_key="unit-placeholder",
            ai_gateway_api_key="unit-placeholder",
        )
        job = {
            "id": "fixture-context-source",
            "organization_id": str(port.scope.organization_id),
            "run_id": str(port.scope.run_id),
            "command_type": "review_case",
        }
        # Supply an observed explanation for the fixture reviewer's exact pointer.
        original = actor.run

        async def run_with_explanation(prompt, *args, **kwargs):
            result = await original(prompt, *args, **kwargs)
            if "case" not in prompt:
                result["output"]["explanation"] = "Explicit fixture with repeated evidence reads."
            return result

        with (
            patch("app.runtime.jobs.HermesActor", return_value=actor),
            patch("app.runtime.jobs.JevClient", return_value=LifecycleJev()),
            patch.object(actor, "run", side_effect=run_with_explanation),
        ):
            observed = await run_job(job, port, settings=settings)
        self.assertEqual(observed["status"], "completed")
        normal_context = actor.loaded_skills[0]
        descriptor = json.loads(
            port.artifacts[
                port.traces[observed["trace"]["id"]]["payload"]["runtime_context_artifact"][
                    "artifact_path"
                ]
            ]
        )
        fixed = descriptor["fixed_context"]
        self.assertEqual(descriptor["immutable_policy"]["id"], "finney-runtime-operations-v1")
        self.assertEqual(
            fixed["prefix"] + DEFAULT_SKILL.read_text() + fixed["suffix"], normal_context
        )
        job.update(
            {
                "id": "fixture-context-learning",
                "command_type": "evaluate_improvement",
                "payload": {"trace_id": observed["trace"]["id"], "suite_id": BLOCKER_SUITE_ID},
            }
        )
        with (
            patch("app.runtime.jobs.HermesActor", return_value=actor),
            patch("app.runtime.jobs.JevClient", return_value=LifecycleJev()),
            patch("app.models.GenerativeModel", return_value=reviewer),
        ):
            evaluated = await run_job(job, port, settings=settings)
        self.assertEqual(evaluated["improvement"]["status"], "promoted")
        diagnosis_input = reviewer.prompts[0]
        self.assertEqual(diagnosis_input["immutable_policy"], descriptor["immutable_policy"])
        self.assertNotEqual(diagnosis_input["immutable_policy"], suite.policy)
        self.assertEqual(diagnosis_input["trace"]["policy_provenance"]["status"], "captured_runtime_context")
        self.assertIn("contract_signals", diagnosis_input["trace"])
        self.assertEqual(diagnosis_input["trace"]["contract_signals"]["procedure_defect"], "not_assessed")
        self.assertNotIn("contract_signals", port.traces[observed["trace"]["id"]]["payload"])
        for context in actor.loaded_skills[1:]:
            self.assertTrue(context.startswith(fixed["prefix"]))
            self.assertTrue(context.endswith(fixed["suffix"]))
        manifest = next(
            json.loads(content)
            for name, content in port.artifacts.items()
            if "evaluation-inputs" in name
        )
        self.assertEqual(manifest["fixed_runtime_context"], fixed)
        self.assertEqual(manifest["observed_trace_policy"], descriptor["immutable_policy"])
        self.assertEqual(manifest["immutable_policy"], suite.policy)

    async def test_director_budget_message_has_bundle_provenance_without_expense_optimization(self):
        from app.runtime.jobs import automatic_improvement_request, ensure_baseline

        port = LifecyclePort()
        await ensure_baseline(port)
        suite = organizer_expense_suite(port, BLOCKER_SUITE_ID)
        actor = LifecycleActor(suite)
        settings = Settings(
            _env_file=None,
            finance_model_api_key="unit-placeholder",
            ai_gateway_api_key="unit-placeholder",
        )
        job = {
            "id": "fixture-budget-message",
            "organization_id": str(port.scope.organization_id),
            "run_id": str(port.scope.run_id),
            "command_type": "director_message",
            "payload": {"message": "Can we afford this in the budget?"},
        }
        with (
            patch("app.runtime.jobs.HermesActor", return_value=actor),
            patch("app.runtime.jobs.JevClient", return_value=LifecycleJev()),
        ):
            outcome = await run_job(job, port, settings=settings)
        self.assertEqual(outcome["status"], "completed")
        trace = port.traces[outcome["trace"]["id"]]["payload"]
        self.assertEqual(trace["skill_version"], "bundle:" + trace["context_sha256"])
        self.assertFalse(trace["improvement_eligible"])
        self.assertNotIn(DEFAULT_SKILL.read_text(), actor.loaded_skills[-1])
        self.assertIsNone(automatic_improvement_request(job, outcome, suite_id=BLOCKER_SUITE_ID))

    async def test_duplicate_attempt_cannot_spend_and_holdout_cannot_be_called_unseen_twice(self):
        first, port, baseline, _actor, _reviewer, suite = await self.attempt(fail="transfer")
        self.assertEqual(first["reason"], "unseen_transfer_failed")

        async def repeat(trace_id):
            actor, reviewer = LifecycleActor(suite), LifecycleReviewer(port)
            outcome = await ImprovementEngine(actor, reviewer, LifecycleJev()).run(
                trace={
                    "id": trace_id,
                    "skill_version": baseline["id"],
                    "tool_events": [],
                    "output": {"explanation": "Declared fixture with redundant source reads."},
                },
                baseline=baseline,
                baseline_content=DEFAULT_SKILL.read_text(),
                suite=suite,
                tools=port,
            )
            return outcome, actor, reviewer

        duplicate, actor, reviewer = await repeat("fixture-trace")
        self.assertEqual(duplicate["reason"], "improvement_attempt_already_claimed")
        self.assertEqual(duplicate["model_call_budget"]["used_upper_bound"], 0)
        self.assertEqual(actor.events, [])
        self.assertEqual(reviewer.prompts, [])
        consumed, actor, _reviewer = await repeat("new-fixture-trace")
        self.assertEqual(consumed["status"], "blocked")
        self.assertEqual(consumed["reason"], "unseen_transfer_already_consumed")
        self.assertEqual(len(actor.events), 6)
        self.assertEqual(port.active, baseline["id"])
        self.assertFalse(any(name == "set_active_skill_version" for name, _ in port.calls))

    async def test_invalid_budget_blocks_before_any_provider_or_claim(self):
        for limit in (0, 41, True):
            with self.subTest(limit=limit):
                port = LifecyclePort()
                suite = organizer_expense_suite(port, BLOCKER_SUITE_ID)
                actor, reviewer = LifecycleActor(suite), LifecycleReviewer(port)
                result = await ImprovementEngine(actor, reviewer, LifecycleJev()).run(
                    trace={},
                    baseline={},
                    baseline_content="",
                    suite=suite,
                    tools=port,
                    max_model_calls=limit,
                )
                self.assertEqual(result["reason"], "evaluation_model_call_budget_invalid")
                self.assertEqual(actor.events, [])
                self.assertEqual(reviewer.prompts, [])
                self.assertFalse(any(name == "claim_improvement_attempt" for name, _ in port.calls))

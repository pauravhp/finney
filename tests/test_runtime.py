"""Boundary checks. Fixtures here are unit tests, never provider evidence."""

import asyncio
import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import Settings
from app.models.providers import ModelConfig, ModelError, parse_json_object
from app.runtime.hermes import ACTOR_TOOLS, APP_ROOT, verify_source
from app.runtime.jobs import (
    DEFAULT_SKILL,
    automatic_improvement_request,
    improvement_review_request,
    run_job,
)
from app.runtime.tool_schemas import schema_for


class RuntimeBoundaries(unittest.TestCase):
    def test_config_requires_explicit_three_values(self):
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(ModelError):
            ModelConfig.from_env()

    def test_key_not_in_repr_and_no_credential_url(self):
        config = ModelConfig("configured-model", "https://example.org/v1", "secret-test-value")
        self.assertNotIn("secret-test-value", repr(config))
        with self.assertRaises(ModelError):
            ModelConfig("x", "https://user:password@example.org/v1", "key")

    def test_only_json_object_accepted(self):
        self.assertEqual(
            parse_json_object('```json\n{"decision":"investigate"}\n```'),
            {"decision": "investigate"},
        )
        self.assertEqual(
            parse_json_object(
                'Here is the result:\n```json\n{"decision":"investigate"}\n```\nAdditional explanation.'
            ),
            {"decision": "investigate"},
        )
        for text in ("done", "[]", 'I think {"done":true}'):
            with self.assertRaises(ModelError):
                parse_json_object(text)

    def test_no_effect_tools_in_actor_allowlist(self):
        self.assertFalse(
            ACTOR_TOOLS
            & {
                "execute_approved_payment",
                "send_approved_message",
                "terminal",
                "browser_navigate",
                "set_active_skill_version",
                "post_ledger",
                "confirm_payment",
                "reserve_approved_payment",
                "transition_payment",
                "draft_followup",
            }
        )
        self.assertTrue({"get_budget_plan", "propose_budget_change"} <= ACTOR_TOOLS)

    @unittest.skipUnless(
        (APP_ROOT / ".runtime/hermes-source/tools/schema_sanitizer.py").exists(),
        "requires bootstrapped pinned source",
    )
    def test_actual_hermes_sanitizer_preserves_kernel_tool_contract(self):
        pinned_source = APP_ROOT / ".runtime/hermes-source"
        verify_source(pinned_source)
        spec = importlib.util.spec_from_file_location(
            "pinned_schema_sanitizer", APP_ROOT / ".runtime/hermes-source/tools/schema_sanitizer.py"
        )
        module = importlib.util.module_from_spec(spec)
        with patch.object(sys, "dont_write_bytecode", True):
            spec.loader.exec_module(module)
        for name, required in {
            "record_finding": {"case_id", "expected_version", "finding", "idempotency_key"},
            "propose_obligation_update": {
                "title",
                "source_refs",
                "amount_minor",
                "idempotency_key",
            },
            "create_approval_request": {"action", "idempotency_key"},
        }.items():
            actual = module.sanitize_tool_schemas(
                [{"type": "function", "function": schema_for(name)}]
            )[0]["function"]["parameters"]
            self.assertTrue(required <= set(actual["required"]))
            self.assertTrue(required <= set(actual["properties"]))
        action = schema_for("create_approval_request")["parameters"]["properties"]["action"]
        self.assertTrue(
            {"destination", "network", "obligation_id", "obligation_version"}
            <= set(action["required"])
        )
        verify_source(pinned_source)

    def test_personal_dotenv_and_revision_drift_block(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / ".env").write_text("not a credential")
            with self.assertRaisesRegex(ModelError, "contains_dotenv"):
                verify_source(source)
            (source / ".env").unlink()
            with self.assertRaisesRegex(ModelError, "source_unavailable"):
                verify_source(source)

    def test_unconfigured_job_is_blocked_without_tool_calls(self):
        class Tools:
            async def call(self, *args):
                raise AssertionError("No access before configured")

        job = {"id": "job", "organization_id": "org", "run_id": "run", "command_type": "intake"}
        with patch.dict("os.environ", {}, clear=True):
            result = asyncio.run(run_job(job, Tools()))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "finance_model_unconfigured")

    def test_supplied_in_memory_settings_do_not_reload_environment(self):
        supplied = Settings(
            _env_file=None,
            finance_model="unit-explicit-model",
            finance_model_api_key="unit-placeholder",
            ai_gateway_api_key="",
        )
        configs, traces = [], []

        class UnitActor:
            def __init__(self, config, **kwargs):
                configs.append(config)

            async def run(self, *args, **kwargs):
                return {
                    "output": {"decision": "unit_no_action"},
                    "tool_events": [],
                    "evidence": {"api_calls": 0},
                }

        class UnitTools:
            async def call(self, name, args):
                if name == "get_active_skill":
                    return {
                        "id": "unit-baseline",
                        "artifact_path": "unit.md",
                        "content_sha256": hashlib.sha256(DEFAULT_SKILL.read_bytes()).hexdigest(),
                    }
                if name == "read_artifact":
                    return {"content": DEFAULT_SKILL.read_text()}
                if name == "put_artifact":
                    return {
                        "artifact_path": "unit-context.json",
                        "content_sha256": hashlib.sha256(args["content"].encode()).hexdigest(),
                    }
                if name == "reserve_run_inference":
                    return {"claimed": True, "reservation_id": args["reservation_id"]}
                if name == "record_trace":
                    traces.append(args)
                    return {"id": "unit-trace"}
                raise AssertionError(name)

        job = {
            "id": "unit-job",
            "organization_id": "unit-org",
            "run_id": "unit-run",
            "command_type": "review_case",
            "requested_by": "unit-initiating-human",
        }
        with (
            patch("app.config.Settings", side_effect=AssertionError("must not reload settings")),
            patch("app.runtime.jobs.HermesActor", UnitActor),
        ):
            result = asyncio.run(run_job(job, UnitTools(), settings=supplied))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(configs[0].model, "unit-explicit-model")
        self.assertEqual(traces[0]["payload"]["initiated_by_user_id"], "unit-initiating-human")

    def test_automatic_review_is_a_deduplicable_hint_after_completed_triage(self):
        job = {"command_type": "review_case"}
        outcome = {
            "status": "completed",
            "triage": {"status": "completed"},
            "trace": {"id": "unit-trace"},
        }
        request = automatic_improvement_request(job, outcome, suite_id="unit-suite")
        self.assertEqual(request["payload"]["trace_id"], "unit-trace")
        self.assertEqual(request["idempotency_key"], "improvement-review:unit-trace")
        for status in ("blocked", "failed"):
            outcome["triage"]["status"] = status
            self.assertIsNone(automatic_improvement_request(job, outcome, suite_id="unit-suite"))

    def test_feedback_cannot_supply_evaluation_or_policy_overrides(self):
        payload = {
            "trace_id": "unit-trace",
            "suite_id": "unit-suite",
            "feedback": "This asked for payer evidence already attached.",
        }
        request = improvement_review_request({"requested_by": "unit-user", "payload": payload})
        self.assertEqual(request["requested_by_user_id"], "unit-user")
        self.assertTrue(request["feedback_is_untrusted_observation"])
        for field in ("expected", "max_model_calls", "required_payment_approvals", "skill"):
            with self.subTest(field=field), self.assertRaises(ModelError):
                improvement_review_request({"payload": {**payload, field: 1}})


if __name__ == "__main__":
    unittest.main()

"""Unit and actual pinned-runtime checks with explicitly scripted upstream responses.

These tests incur no model calls and are not evidence of model quality.
"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import httpx

from app.finance.tools import FinanceToolClient
from app.finance.types import Scope
from app.models.providers import ModelConfig, ModelError
from app.runtime.hermes import ACTOR_TOOLS
from app.runtime.opencode import (
    OpenCodeActor,
    OpenCodeActorError,
    _configuration,
    _environment,
    output_schema,
)
from app.runtime.opencode_bridge import MAX_PROVIDER_ERROR_BYTES, FinanceBridge
from app.runtime.opencode_setup import DEFAULT_BINARY, PIN, verify_binary

CONFIG = ModelConfig("claude-sonnet-4-6", "https://unit.invalid/v1", "unit-secret-provider-key",
                     api_mode="anthropic_messages", max_tokens=1600)
DECISION = {"decision": "investigate", "explanation": "Source read; no payment authority.",
            "evidence_source_ids": ["unit-source"], "clarification": None,
            "proposed_action": None, "blocking_requirements": []}


class UnitTools:
    def __init__(self):
        self.calls = []

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        return {"status": "completed", "id": "unit-case", "source_refs": [{"id": "unit-source", "version": 1}]}


def anthropic_response(name=None, arguments=None, *, text=None, stop_reason=None):
    """An explicit upstream fixture, consumed by the actual OpenCode AI SDK."""
    events = [{"type": "message_start", "message": {
        "id": "unit-msg", "type": "message", "role": "assistant", "model": CONFIG.model,
        "content": [], "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 20, "output_tokens": 0},
    }}]
    if name:
        events += [
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "tool_use", "id": "unit-call", "name": name, "input": {}}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "input_json_delta", "partial_json": json.dumps(arguments)}},
        ]
    else:
        events += [
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": text or "Unit answer."}},
        ]
    events += [
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {
            "stop_reason": stop_reason or ("tool_use" if name else "end_turn"), "stop_sequence": None,
        }, "usage": {"output_tokens": 12}},
        {"type": "message_stop"},
    ]
    return httpx.Response(200, headers={"content-type": "text/event-stream", "request-id": "unit-request"},
                          content="".join("event: " + e["type"] + "\ndata: " + json.dumps(e) + "\n\n" for e in events))


class BridgeBoundaries(unittest.IsolatedAsyncioTestCase):
    def test_configured_binary_accepts_settings_string(self):
        actor = OpenCodeActor(CONFIG, binary="/tmp/explicit-opencode")
        self.assertEqual(actor.binary, Path("/tmp/explicit-opencode"))

    async def test_mcp_exposes_only_allowlist_and_denies_other_effects(self):
        tools = UnitTools()
        async with FinanceBridge(CONFIG, tools, frozenset({"get_case"}), 2, structured=True) as bridge:
            async with httpx.AsyncClient(trust_env=False) as client:
                r = await client.post(bridge.url + "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
                self.assertEqual(r.status_code, 401)
                headers = {"Authorization": "Bearer " + bridge.token}
                r = await client.post(bridge.url + "/mcp", headers=headers,
                                      json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
                self.assertEqual([x["name"] for x in r.json()["result"]["tools"]], ["get_case"])
                for name in ("bash", "execute_approved_payment", "set_active_skill_version"):
                    r = await client.post(bridge.url + "/mcp", headers=headers, json={
                        "jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": {}},
                    })
                    result = json.loads(r.json()["result"]["content"][0]["text"])
                    self.assertEqual(result["error"], "tool_not_permitted")
            self.assertEqual(tools.calls, [])

    async def test_provider_hard_budget_and_token_cap(self):
        seen = []

        def respond(request):
            seen.append(json.loads(request.content))
            self.assertEqual(request.headers["x-api-key"], CONFIG.api_key)
            return anthropic_response("StructuredOutput", DECISION)

        async with FinanceBridge(CONFIG, UnitTools(), frozenset(), 1, structured=True) as bridge:
            bridge._client._transport = httpx.MockTransport(respond)
            payload = {"model": CONFIG.model, "max_tokens": 99999, "stream": True,
                       "tools": [{"name": "StructuredOutput"}]}
            status, _, _ = await bridge.provider(payload)
            self.assertEqual(status, 200)
            self.assertEqual(seen[0]["max_tokens"], 1600)
            self.assertEqual(bridge.usage, {"input_tokens": 20, "output_tokens": 12})
            self.assertEqual(bridge.request_ids, ["unit-request"])
            status, _, _ = await bridge.provider(payload)
            self.assertEqual(status, 400)
            self.assertEqual(bridge.failure_code, "evaluation_model_call_budget_exhausted")
            self.assertEqual(len(seen), 1)

    async def test_provider_error_prefix_is_finite_private_redacted_and_not_retried(self):
        class EndlessError(httpx.AsyncByteStream):
            def __init__(self):
                self.reads, self.closed = 0, False

            async def __aiter__(self):
                while True:
                    self.reads += 1
                    yield (CONFIG.api_key + "|private-provider-error|" + "x" * 4096).encode()

            async def aclose(self):
                self.closed = True

        stream, seen = EndlessError(), []

        def respond(request):
            seen.append(request)
            return httpx.Response(400, stream=stream)

        async with FinanceBridge(CONFIG, UnitTools(), frozenset(), 1, structured=True) as bridge:
            bridge._client._transport = httpx.MockTransport(respond)
            for _ in range(2):
                status, _, public = await bridge.provider({"model": CONFIG.model})
                self.assertEqual(status, 400)
                self.assertNotIn(b"private-provider-error", public)
            private = bridge.private_provider_error
            self.assertEqual(private["http_status"], 400)
            self.assertTrue(private["truncated"])
            self.assertLessEqual(len(private["body"].encode()), MAX_PROVIDER_ERROR_BYTES)
            self.assertNotIn(CONFIG.api_key, private["body"])
            self.assertNotIn("private-provider-error", json.dumps(bridge.calls))
            self.assertEqual(len(seen), 1)
            self.assertLess(stream.reads, 20)
            self.assertTrue(stream.closed)

    async def test_provider_error_capture_redacts_secret_cut_at_boundary_and_caps_invalid_utf8(self):
        async with FinanceBridge(CONFIG, UnitTools(), frozenset(), 1, structured=True) as bridge:
            prefix_size = MAX_PROVIDER_ERROR_BYTES - 10
            body = b"x" * prefix_size + CONFIG.api_key.encode() + b"more"
            response = httpx.Response(400, content=body)
            await bridge._capture_provider_error(response)
            self.assertNotIn(CONFIG.api_key[:10], bridge.private_provider_error["body"])
            self.assertLessEqual(len(bridge.private_provider_error["body"].encode()), MAX_PROVIDER_ERROR_BYTES)
            await bridge._capture_provider_error(httpx.Response(500, content=b"\xff" * MAX_PROVIDER_ERROR_BYTES))
            self.assertLessEqual(len(bridge.private_provider_error["body"].encode()), MAX_PROVIDER_ERROR_BYTES)

    async def test_step_hint_does_not_trigger_prefill_on_the_last_authorized_call(self):
        async with FinanceBridge(CONFIG, UnitTools(), frozenset(), 1, structured=True) as bridge:
            config = _configuration(CONFIG, bridge, "unit editor", 1)
            self.assertEqual(config["agent"]["finance"]["steps"], 2)
            self.assertEqual(bridge.limit, 1)

    async def test_upstream_failure_latches_without_retry_or_secret_error(self):
        seen = []

        def respond(request):
            seen.append(request)
            return httpx.Response(401, text=CONFIG.api_key)

        async with FinanceBridge(CONFIG, UnitTools(), frozenset(), 8, structured=True) as bridge:
            bridge._client._transport = httpx.MockTransport(respond)
            for _ in range(3):
                status, _, body = await bridge.provider({"model": CONFIG.model})
                self.assertEqual(status, 400)
                self.assertNotIn(CONFIG.api_key.encode(), body)
            self.assertEqual(len(seen), 1)
            self.assertEqual(len(bridge.calls), 1)
            self.assertEqual(bridge.calls[0]["http_status"], 401)

    async def test_unexpected_runtime_tool_or_model_never_reaches_provider(self):
        for extra in ({"model": "other-model"}, {"tools": [{"name": "bash"}]}):
            async with FinanceBridge(CONFIG, UnitTools(), frozenset(), 8, structured=True) as bridge:
                status, _, _ = await bridge.provider({"model": CONFIG.model, **extra})
                self.assertEqual(status, 400)
                self.assertEqual(bridge.calls, [])

    async def test_provider_stream_without_terminal_marker_fails(self):
        def respond(request):
            response = anthropic_response("StructuredOutput", DECISION)
            raw = response.content.split(b"event: message_stop")[0]
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=raw)

        async with FinanceBridge(CONFIG, UnitTools(), frozenset(), 1, structured=True) as bridge:
            bridge._client._transport = httpx.MockTransport(respond)
            status, _, _ = await bridge.provider({"model": CONFIG.model})
            self.assertEqual(status, 400)
            self.assertEqual(bridge.failure_code, "provider_incomplete_stream")

    async def test_tool_exception_and_known_secret_echo_are_safe(self):
        class FailingTools:
            async def call(self, *_):
                raise RuntimeError(CONFIG.api_key)

        async with FinanceBridge(CONFIG, FailingTools(), frozenset({"get_case"}), 1, structured=True) as bridge:
            _, result = await bridge.mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "get_case", "arguments": {"case_id": CONFIG.api_key},
            }})
            self.assertNotIn(CONFIG.api_key, json.dumps(result) + json.dumps(bridge.events))
            self.assertEqual(bridge.events[0]["result"]["error"], "finance_tool_error")

    async def test_config_is_denied_by_default_and_child_receives_no_provider_secret(self):
        async with FinanceBridge(CONFIG, UnitTools(), frozenset({"get_case"}), 2, structured=True) as bridge:
            config = _configuration(CONFIG, bridge, "unit skill", 2)
            self.assertEqual(config["permission"]["*"], "deny")
            self.assertEqual(config["permission"]["StructuredOutput"], "allow")
            self.assertEqual(config["permission"]["finance_get_case"], "allow")
            self.assertNotIn(CONFIG.api_key, json.dumps(config))
            env = _environment(Path("/tmp/unit-isolated"), "unit-password")
            self.assertNotIn(CONFIG.api_key, json.dumps(env))
            for name in ("HTTP_PROXY", "ANTHROPIC_API_KEY", "FINANCE_MODEL_API_KEY", "HERMES_HOME"):
                self.assertNotIn(name, env)
            self.assertTrue(all(env[key].startswith("/tmp/unit-isolated") for key in (
                "HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME",
            )))

    async def test_invalid_allowance_never_launches_process(self):
        with patch("app.runtime.opencode.verify_binary"), patch("asyncio.create_subprocess_exec") as launch:
            for budget in (0, -1, True, 1.5):
                with self.assertRaisesRegex(ModelError, "model_call_budget"):
                    await OpenCodeActor(CONFIG).run({}, "", UnitTools(), max_model_calls=budget)
            launch.assert_not_called()

    async def test_binary_drift_and_symlink_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "opencode"
            binary.write_bytes(b"untrusted executable")
            with self.assertRaisesRegex(ModelError, "revision_mismatch"):
                verify_binary(binary)
            alias = Path(directory) / "alias"
            alias.symlink_to(binary)
            with self.assertRaisesRegex(ModelError, "symlink"):
                verify_binary(alias)

    def test_decision_schema_has_nonempty_source_linked_blockers(self):
        schema = output_schema("finance")
        refs = schema["properties"]["blocking_requirements"]["items"]["properties"]["supporting_refs"]
        self.assertEqual(refs["minItems"], 1)
        self.assertFalse(ACTOR_TOOLS & {"bash", "read", "edit", "execute_approved_payment"})


@unittest.skipUnless(DEFAULT_BINARY.exists(), "requires explicitly installed pinned OpenCode")
class ActualOpenCodeWithFixtureProvider(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, responses, *, prompt=None, limit=3, timeout=45, mode="finance", tools=None, allowed=None, reject_assistant_prefill=False):
        seen, bridges = [], []
        tools = tools if tools is not None else UnitTools()

        def respond(request):
            payload = json.loads(request.content)
            seen.append(payload)
            if reject_assistant_prefill and payload.get("messages", [{}])[-1].get("role") == "assistant":
                return httpx.Response(400, json={"error": {"message": "This model does not support assistant message prefill."}})
            self.assertTrue(request.url.host == "unit.invalid")
            names = {tool.get("name") for tool in payload.get("tools", [])}
            self.assertFalse(names & {"bash", "edit", "read", "webfetch", "task", "skill"})
            response = responses[min(len(seen) - 1, len(responses) - 1)]
            return response() if callable(response) else response

        class FixtureBridge(FinanceBridge):
            async def __aenter__(self):
                await self._client.aclose()
                self._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
                bridges.append(self)
                return await super().__aenter__()

        with patch("app.runtime.opencode.FinanceBridge", FixtureBridge):
            result = await OpenCodeActor(CONFIG, timeout_seconds=timeout, mode=mode).run(
                prompt or {"case_id": "unit-case"}, "Read the linked case before deciding.", tools,
                allowed_tools=allowed or frozenset({"get_case", "check_setup"}), max_model_calls=limit,
            )
        return result, tools, seen, bridges

    async def test_real_runtime_mcp_then_structured_finance_response(self):
        result, tools, seen, bridges = await self.invoke([
            lambda: anthropic_response("finance_get_case", {"case_id": "unit-case"}),
            lambda: anthropic_response("StructuredOutput", DECISION),
        ])
        self.assertEqual(result["output"], DECISION)
        self.assertEqual(tools.calls, [("get_case", {"case_id": "unit-case"})])
        self.assertEqual(result["evidence"]["runtime"], "opencode")
        self.assertEqual(result["evidence"]["version"], PIN["version"])
        self.assertEqual(result["evidence"]["api_calls"], 2)
        self.assertEqual(result["evidence"]["usage"], {"input_tokens": 40, "output_tokens": 24})
        self.assertEqual(len(bridges[0].calls), 2)
        self.assertEqual(seen[0]["max_tokens"], 1600)

    async def test_real_runtime_editor_has_only_structured_output(self):
        expected = {"procedure": None, "notes": "No supported change.", "experience": None}
        result, tools, seen, _ = await self.invoke([
            lambda: anthropic_response("StructuredOutput", expected),
        ], mode="editor", limit=1)
        self.assertEqual(result["output"], expected)
        self.assertEqual(tools.calls, [])
        self.assertEqual(result["evidence"]["api_calls"], 1)
        self.assertEqual({t["name"] for t in seen[0].get("tools", [])}, {"StructuredOutput"})

    async def test_real_runtime_one_call_editor_does_not_send_assistant_prefill(self):
        expected = {"procedure": None, "notes": "No supported change."}
        result, tools, seen, _ = await self.invoke([
            lambda: anthropic_response("StructuredOutput", expected),
        ], mode="editor", limit=1, reject_assistant_prefill=True)
        self.assertEqual(result["output"], expected)
        self.assertEqual(tools.calls, [])
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["messages"][-1]["role"], "user")
        self.assertEqual({t["name"] for t in seen[0].get("tools", [])}, {"StructuredOutput"})
        self.assertEqual(result["evidence"]["api_calls"], 1)

    async def test_real_runtime_provider_error_body_is_only_in_private_diagnostic(self):
        message = "private-provider-message: unsupported assistant prefill; " + CONFIG.api_key
        with self.assertRaises(OpenCodeActorError) as caught:
            await self.invoke([httpx.Response(400, json={"error": {"message": message}})], mode="editor", limit=1)
        private = caught.exception.private_diagnostic
        self.assertEqual(private["provider_error"]["http_status"], 400)
        self.assertIn("private-provider-message", private["provider_error"]["body"])
        self.assertNotIn(CONFIG.api_key, json.dumps(private))
        self.assertNotIn("private-provider-message", json.dumps(private["provider_calls"]))
        self.assertNotIn("private-provider-message", str(caught.exception))
        self.assertEqual(private["api_calls"], 1)

    async def test_real_runtime_rejects_bare_uuid_financial_references(self):
        output = {**DECISION, "proposed_action": {"action": "pay_vendor", "amount_minor": 100,
            "currency": "USD", "evidence_refs": ["unit-source"]}}
        with self.assertRaisesRegex(OpenCodeActorError, "invalid_finance_decision_schema"):
            await self.invoke([lambda: anthropic_response("StructuredOutput", output)], limit=1)

    async def test_real_runtime_director_text_contract(self):
        result, tools, _, _ = await self.invoke([
            lambda: anthropic_response("finance_get_case", {"case_id": "unit-case"}),
            lambda: anthropic_response(text="The source is reported; cash remains unknown."),
        ], prompt={"command_type": "director_message", "message": "What is the status?"})
        self.assertEqual(result["output"]["response_type"], "director_response")
        self.assertEqual(result["evidence"]["output_contract"], "finance-director-response-v1")
        self.assertEqual(len(tools.calls), 1)

    async def test_real_runtime_genuine_prepare_only_finance_client_preserves_array_results(self):
        class ForbiddenNetwork:
            async def rpc(self, *_args, **_kwargs):
                raise AssertionError("prepare-only reads must not reach the database")

        scope = Scope(UUID(int=1), UUID(int=2))
        obligations = [{"id": "unit-open-obligation", "currency": "USD", "amount_minor": "12500",
                        "settled_minor": "5000", "status": "open", "direction": "payable"}]
        open_case = {"id": "unit-open-case", "status": "open"}
        tools = FinanceToolClient(scope, ForbiddenNetwork()).for_evaluation({
            "organization": {"id": str(scope.organization_id)}, "run": {"id": str(scope.run_id)},
            "obligations": obligations, "cases": [open_case, {"id": "unit-closed-case", "status": "closed"}],
        })
        result, _, seen, _ = await self.invoke([
            lambda: anthropic_response("finance_get_obligations", {}),
            lambda: anthropic_response("finance_list_due_work", {}),
            lambda: anthropic_response("StructuredOutput", DECISION),
        ], tools=tools, allowed=frozenset({"get_obligations", "list_due_work"}))
        self.assertTrue(tools.prepare_only)
        self.assertEqual(result["tool_events"][0]["result"], obligations)
        self.assertEqual(result["tool_events"][1]["result"], [open_case])
        self.assertIn("unit-open-obligation", json.dumps(seen[1]))
        self.assertNotIn("finance_tool_error", json.dumps(seen))

    async def test_real_runtime_call_budget_exhaustion_stays_private(self):
        with self.assertRaises(OpenCodeActorError) as caught:
            await self.invoke([lambda: anthropic_response("finance_get_case", {"case_id": "unit-case"})], limit=1)
        self.assertEqual(caught.exception.code, "evaluation_model_call_budget_exhausted")
        private = caught.exception.private_diagnostic
        self.assertEqual(private["api_calls"], 1)
        self.assertEqual(len(private["tool_events"]), 1)
        self.assertNotIn(CONFIG.api_key, json.dumps(private))
        self.assertNotIn("tool_events", str(caught.exception))

    async def test_real_runtime_upstream_auth_failure_no_retry(self):
        with self.assertRaises(OpenCodeActorError) as caught:
            await self.invoke([httpx.Response(401, text=CONFIG.api_key)])
        self.assertEqual(caught.exception.code, "provider_http_error")
        self.assertEqual(caught.exception.private_diagnostic["api_calls"], 1)
        self.assertNotIn(CONFIG.api_key, json.dumps(caught.exception.private_diagnostic))

    async def test_real_runtime_truncation_is_failure(self):
        with self.assertRaises(OpenCodeActorError) as caught:
            await self.invoke([lambda: anthropic_response("StructuredOutput", DECISION, stop_reason="max_tokens")])
        self.assertEqual(caught.exception.code, "opencode_truncated_output")

    async def test_real_runtime_onboarding_schema(self):
        output = {"status": "blocked", "next_action": "Configure provider", "instructions": "Use environment.",
                  "blocked_checks": ["model"]}
        result, tools, _, _ = await self.invoke([
            lambda: anthropic_response("finance_check_setup", {}),
            lambda: anthropic_response("StructuredOutput", output),
        ], mode="onboarding")
        self.assertEqual(result["output"], output)
        self.assertEqual(tools.calls, [("check_setup", {})])

    async def test_real_runtime_hallucinated_builtin_cannot_execute(self):
        # The response bridge blocks an unadvertised tool before OpenCode receives it.
        with self.assertRaises(OpenCodeActorError) as caught:
            await self.invoke([
                lambda: anthropic_response("bash", {"command": "touch /tmp/finney-denied-tool-marker"}),
            ])
        self.assertEqual(caught.exception.code, "opencode_tool_not_permitted")
        self.assertEqual(caught.exception.private_diagnostic["tool_events"][0]["result"]["status"], "blocked")
        self.assertFalse(Path("/tmp/finney-denied-tool-marker").exists())

    async def test_real_runtime_malformed_structured_output_fails_with_private_final_text(self):
        with self.assertRaises(OpenCodeActorError) as caught:
            await self.invoke([lambda: anthropic_response(text="A final answer without the required schema.")])
        self.assertEqual(caught.exception.code, "opencode_provider_or_runtime_failure")
        self.assertEqual(caught.exception.private_diagnostic["original_final_response"],
                         "A final answer without the required schema.")

    async def test_real_runtime_finance_report_extension(self):
        output = {**DECISION, "finance_report": {"cash_minor": None, "reported_payable_minor": 12500,
                                               "currency": "USD"}}
        result, _, _, _ = await self.invoke([lambda: anthropic_response("StructuredOutput", output)])
        self.assertEqual(result["output"], output)

    async def test_real_runtime_invalid_blocker_keeps_original_json_on_deterministic_rejection(self):
        output = {**DECISION, "blocking_requirements": [{"stage": "approval_request",
            "requirement": "source_documents", "supporting_refs": []}]}
        with self.assertRaises(OpenCodeActorError) as caught:
            await self.invoke([lambda: anthropic_response("StructuredOutput", output)], limit=1)
        self.assertEqual(caught.exception.code, "invalid_finance_decision_schema")
        self.assertEqual(json.loads(caught.exception.private_diagnostic["original_final_response"]), output)

    async def test_real_runtime_timeout_kills_process_and_deletes_temporary_profile(self):
        launched = []
        create_process = asyncio.create_subprocess_exec

        async def record_process(*args, **kwargs):
            process = await create_process(*args, **kwargs)
            launched.append((process, Path(kwargs["cwd"]).parent))
            return process

        with (patch("asyncio.create_subprocess_exec", record_process),
              self.assertRaises(OpenCodeActorError) as caught):
            await self.invoke([lambda: anthropic_response("StructuredOutput", DECISION)], timeout=0.2)
        self.assertEqual(caught.exception.code, "opencode_timeout")
        self.assertEqual(len(launched), 1)
        self.assertIsNotNone(launched[0][0].returncode)
        self.assertFalse(launched[0][1].exists())


if __name__ == "__main__":
    unittest.main()

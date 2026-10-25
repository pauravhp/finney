"""Transport/process fixtures; no model or hosted calls. SQL guards are unchanged."""
import json

import httpx
import pytest
from test_runtime_format import DECISION, FakeProcess

from app.models.providers import ModelConfig
from app.runtime import hermes
from app.runtime.opencode_bridge import FinanceBridge
from app.runtime.tool_errors import safe_tool_failure
from app.storage.supabase import SupabaseClient, SupabaseError

SQL_MESSAGE = "source reference missing, stale or outside run"
PRIVATE = "PRIVATE-PROVIDER-BODY-AND-CREDENTIAL"
CONFIG = ModelConfig("fixture-model", "https://fixture.invalid/v1", "fixture-key")


@pytest.mark.parametrize("status,code,message,path,expected", [
    (400, "23514", SQL_MESSAGE, "finance_kernel_call", "source_reference_not_current"),
    (400, "23514", "current versioned source references required", "finance_kernel_call", "source_references_required"),
    (400, "23514", "invalid source references", "finance_kernel_call", "source_references_invalid"),
    (400, "23514", SQL_MESSAGE + PRIVATE, "finance_kernel_call", None),
    (400, "P0001", SQL_MESSAGE, "finance_kernel_call", None),
    (403, "23514", SQL_MESSAGE, "finance_kernel_call", None),
    (401, "23514", SQL_MESSAGE, "finance_kernel_call", None),
    (503, "23514", SQL_MESSAGE, "finance_kernel_call", None),
    (400, "23514", SQL_MESSAGE, "other_rpc", None),
    (400, "23514", {"secret": PRIVATE}, "finance_kernel_call", None),
])
async def test_only_exact_known_kernel_rejection_becomes_fixed_domain_reason(status, code, message, path, expected):
    requests = []
    async def respond(request):
        requests.append(request)
        return httpx.Response(status, json={"code": code, "message": message,
                                           "details": PRIVATE, "hint": PRIVATE})

    async with SupabaseClient("https://fixture.invalid", "fixture-key",
                              transport=httpx.MockTransport(respond)) as db:
        with pytest.raises(SupabaseError) as caught:
            await db.rpc(path, {})
    assert len(requests) == 1
    assert caught.value.domain_reason == expected
    projected = safe_tool_failure(caught.value)
    assert PRIVATE not in str(caught.value) + repr(vars(caught.value)) + json.dumps(projected)
    if expected:
        assert projected["error"] == "finance_domain_rejection"
        assert projected["reason"] == expected
        assert projected["retry_unchanged"] is False
    else:
        assert projected == {"status": "failed", "error": "finance_tool_error", "error_type": "SupabaseError"}


def test_untrusted_exception_text_is_never_projected_as_domain_guidance():
    assert safe_tool_failure(RuntimeError(SQL_MESSAGE + PRIVATE)) == {
        "status": "failed", "error": "finance_tool_error", "error_type": "RuntimeError"}
    assert SupabaseError(400, "23514", domain_reason=PRIVATE).domain_reason is None
    assert SupabaseError(403, "23514", domain_reason="source_reference_not_current").domain_reason is None


class RejectedTools:
    def __init__(self, db):
        self.db = db

    async def call(self, name, args):
        return await self.db.rpc("finance_kernel_call", {"p_operation": name, "p_arguments": args})


def rejection(request):
    return httpx.Response(400, json={"code": "23514", "message": SQL_MESSAGE, "details": PRIVATE})


async def test_opencode_receives_and_records_safe_actionable_rejection():
    async with (
        SupabaseClient("https://fixture.invalid", "fixture-key",
                       transport=httpx.MockTransport(rejection)) as db,
        FinanceBridge(CONFIG, RejectedTools(db), frozenset({"propose_obligation_update"}), 1,
                      structured=True) as bridge,
    ):
        _, result = await bridge.mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": "propose_obligation_update", "arguments": {}}})
        assert result["result"]["isError"] is True
        actor_result = json.loads(result["result"]["content"][0]["text"])
        assert actor_result == bridge.events[0]["result"]
        assert actor_result["reason"] == "source_reference_not_current"
        assert PRIVATE not in json.dumps(result) + json.dumps(bridge.events)


async def test_hermes_receives_same_safe_rejection_without_replaying_tool(monkeypatch):
    process = FakeProcess([
        {"type": "tool_call", "name": "propose_obligation_update", "arguments": {}},
        {"type": "result", "result": {"final_response": json.dumps(DECISION), "api_calls": 2,
                                       "completed": True, "failed": False, "partial": False}},
    ])
    monkeypatch.setattr(hermes, "verify_source", lambda source: None)
    async def spawn(*args, **kwargs):
        return process
    monkeypatch.setattr(hermes.asyncio, "create_subprocess_exec", spawn)
    async with SupabaseClient("https://fixture.invalid", "fixture-key",
                              transport=httpx.MockTransport(rejection)) as db:
        result = await hermes.HermesActor(CONFIG).run({}, "Unchanged fixture procedure", RejectedTools(db))
    actor_result = process.stdin.writes[1]["result"]
    assert actor_result == result["tool_events"][0]["result"]
    assert actor_result["reason"] == "source_reference_not_current"
    assert len(result["tool_events"]) == 1
    assert PRIVATE not in json.dumps(result) + json.dumps(process.stdin.writes)

"""Safe runtime diagnostics using local storage/engine fixtures; no inference."""
import json
from uuid import uuid4

import pytest
from test_improvement_lifecycle import LifecyclePort

from app.config import Settings
from app.improvement.blockers import BLOCKER_SUITE_ID
from app.runtime.jobs import _runtime_failure_detail, ensure_baseline, run_job
from app.storage.supabase import SupabaseError

PRIVATE = "PRIVATE-ERROR-MESSAGE-CREDENTIAL-BODY"


def job(port, command="review_case"):
    return {"id": str(uuid4()), "organization_id": str(port.scope.organization_id),
            "run_id": str(port.scope.run_id), "command_type": command,
            "payload": {}, "attempts": 2}


async def test_uncaught_runtime_failure_gets_durable_safe_stage_and_compact_queue_reason(monkeypatch):
    port = LifecyclePort()
    baseline = await ensure_baseline(port)
    trace_id = str(uuid4())
    port.traces[trace_id] = {"id": trace_id, "event_type": "actor_completed", "payload": {
        "skill_version": baseline["id"], "tool_events": [], "output": {},
    }}
    request = job(port, "evaluate_improvement")
    request["payload"] = {"trace_id": trace_id, "suite_id": BLOCKER_SUITE_ID}

    async def failure(*args, **kwargs):
        secret_local = PRIVATE
        raise UnicodeDecodeError("utf-8", secret_local.encode(), 0, 1, PRIVATE)

    monkeypatch.setattr("app.improvement.engine.ImprovementEngine.run", failure)
    result = await run_job(request, port, settings=Settings(
        _env_file=None, finance_model_api_key="fixture", ai_gateway_api_key="fixture"))
    assert result["status"] == "failed" and result["retryable"] is False
    assert result["reason"] == "runtime_failure:improvement_run:UnicodeDecodeError"
    assert len(result["reason"]) < 100
    receipt = next(row for row in port.traces.values() if row["event_type"] == "runtime_job_failed")
    payload = receipt["payload"]
    assert payload["job_attempt"] == 2 and payload["stage"] == "improvement_run"
    assert any(frame["file"] == "runtime/jobs.py" and frame["function"] == "run_job"
               for frame in payload["frames"])
    assert all(set(frame) == {"file", "line", "function"} for frame in payload["frames"])
    assert PRIVATE not in json.dumps(result) + json.dumps(receipt)
    assert "/home/" not in json.dumps(receipt)
    assert not port.holdouts and not port.promotions
    assert all(name != "finish_improvement_attempt" for name, _ in port.calls)


async def test_failed_diagnostic_write_keeps_primary_error_and_never_retries_model():
    port = LifecyclePort()
    attempts = []

    async def call(name, args):
        attempts.append(name)
        if name == "get_active_skill":
            raise ValueError(PRIVATE)
        if name == "record_trace":
            raise RuntimeError(PRIVATE)
        pytest.fail("No other operation is allowed after this fixture failure")

    port.call = call
    result = await run_job(job(port), port, settings=Settings(_env_file=None, finance_model_api_key="fixture"))
    assert result["reason"] == "runtime_failure:baseline_load:ValueError"
    assert result["failure_trace"] == {"status": "unavailable", "error_type": "RuntimeError"}
    assert attempts == ["get_active_skill", "record_trace"]
    assert PRIVATE not in json.dumps(result)


@pytest.mark.parametrize("status", [401, 403])
async def test_authorization_failure_does_not_try_privileged_diagnostic_write(status):
    port = LifecyclePort()
    attempts = []
    async def call(name, args):
        attempts.append(name)
        raise SupabaseError(status, "42501")
    port.call = call
    result = await run_job(job(port), port, settings=Settings(_env_file=None, finance_model_api_key="fixture"))
    assert result["reason"] == "runtime_failure:baseline_load:SupabaseError"
    assert result["failure_trace"]["reason"] == "authorization_failed"
    assert attempts == ["get_active_skill"]


def test_unknown_exception_names_and_database_codes_are_not_exported():
    private_class = type(PRIVATE, (Exception,), {})
    detail = _runtime_failure_detail(private_class(PRIVATE), "actor_run")
    assert detail["error_type"] == "Exception"
    assert PRIVATE not in json.dumps(detail)
    detail = _runtime_failure_detail(SupabaseError(400, PRIVATE), "improvement_run")
    assert detail["database_code"] == "provider_error"
    assert PRIVATE not in json.dumps(detail)
    assert _runtime_failure_detail(SupabaseError(400, "22023"), "improvement_run")["database_code"] == "22023"

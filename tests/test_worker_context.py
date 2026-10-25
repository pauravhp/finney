"""Wake orientation fixtures; no provider/model calls or invented ledger evidence."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.finance.types import FinanceError
from app.worker_context import WorkerWakeCheck


class Tools:
    def __init__(self, run=2):
        self.scope = SimpleNamespace(organization_id=UUID(int=1), run_id=UUID(int=run))
        self.calls = []
        self.snapshot = {
            "organization": {"id": str(self.scope.organization_id)},
            "run": {"id": str(self.scope.run_id), "revision": 7},
            "updated_at": "2026-10-25T10:00:00Z",
            "position": {"currency": "USD", "cash_minor": None, "evidence_status": "unknown"},
            "cases": [{"data": {"private_text": "not copied into wake audit"}}],
            "obligations": [{"amount_minor": "15327"}],
            "approvals": [{"status": "pending"}, {"status": "rejected"}],
            "connections": [{"provider": "gmail", "status": "connected", "mailbox": "private"}],
        }
        self.fail_receipt = False

    async def call(self, name, args):
        self.calls.append((name, deepcopy(args)))
        if name == "get_finance_snapshot":
            return deepcopy(self.snapshot)
        if name == "record_trace":
            if self.fail_receipt:
                raise RuntimeError("fixture receipt unavailable")
            return {"id": "fixture-receipt"}
        raise AssertionError("Wake must not execute financial or model tools")


async def test_wake_reads_current_state_once_per_scope_and_preserves_unknown_cash():
    checker, tools = WorkerWakeCheck(), Tools()
    await checker.check(tools)
    await checker.check(tools)
    assert [name for name, _ in tools.calls] == ["get_finance_snapshot", "record_trace"]
    receipt = tools.calls[-1][1]
    assert receipt["event_type"] == "worker_finance_wake"
    payload = receipt["payload"]
    assert payload["position"]["cash_minor"] is None
    assert payload["pending_approval_count"] == payload["rejected_approval_count"] == 1
    assert payload["coverage"] == "recorded_finance_state_only"
    assert "private" not in str(payload)
    other = Tools(run=3)
    await checker.check(other)
    assert len(other.calls) == 2
    assert len(checker.checked) == 2


async def test_failed_wake_receipt_does_not_mark_scope_checked():
    checker, tools = WorkerWakeCheck(), Tools()
    tools.fail_receipt = True
    with pytest.raises(RuntimeError, match="receipt unavailable"):
        await checker.check(tools)
    assert not checker.checked
    tools.fail_receipt = False
    tools.snapshot["run"]["revision"] = 99
    await checker.check(tools)
    assert len(checker.checked) == 1
    assert tools.calls[-1][1] == tools.calls[-2][1]
    assert tools.calls[-1][1]["payload"]["run_revision"] == 7


async def test_wake_refuses_cross_scope_snapshot_before_recording():
    checker, tools = WorkerWakeCheck(), Tools()
    tools.snapshot["run"]["id"] = str(UUID(int=9))
    with pytest.raises(FinanceError, match="scope_mismatch"):
        await checker.check(tools)
    assert [name for name, _ in tools.calls] == ["get_finance_snapshot"]
    assert not checker.checked


@pytest.mark.parametrize("command", ["director_message", "review_case", "intake"])
async def test_worker_wake_precedes_actor_but_does_not_add_provider_work_to_intake(monkeypatch, command):
    from app.cli import run_worker
    from app.config import Settings

    tools = Tools()
    outcomes = []
    job = {"id": "fixture-job", "organization_id": str(tools.scope.organization_id),
           "run_id": str(tools.scope.run_id), "lease_token": "fixture-lease",
           "command_type": command, "payload": {}}

    class DB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Queue:
        def __init__(self, *args):
            pass

        async def lease(self, **kwargs):
            return job

        async def ack(self, job_id, lease_token, result):
            outcomes.append(result)

        async def fail(self, *args, **kwargs):
            pytest.fail("Worker fixture should complete")

    async def dispatch(settings, actual_job, actual_tools, client):
        assert actual_job is job and actual_tools is tools
        assert len(tools.calls) == (0 if command == "intake" else 2)
        return {"status": "completed"}

    monkeypatch.setattr("app.storage.supabase.SupabaseClient", lambda *args, **kwargs: DB())
    monkeypatch.setattr("app.finance.jobs.JobQueue", Queue)
    monkeypatch.setattr("app.finance.tools.FinanceToolClient", lambda *args, **kwargs: tools)
    monkeypatch.setattr("app.service.dispatch_job", dispatch)
    monkeypatch.setattr("app.cli.install_runtime_environment", lambda settings: None)
    await run_worker(Settings(_env_file=None, supabase_url="https://fixture.invalid",
                              supabase_secret_key="fixture-only"), once=True)
    assert outcomes == [{"status": "completed"}]

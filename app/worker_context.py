"""Read-only finance orientation when a worker first handles a scope after waking.

The audit is trusted application bookkeeping, not an agent decision, a bank
reconciliation or a claim that every relevant email has arrived.
"""
from __future__ import annotations

from uuid import uuid4

from app.finance.types import FinanceError


class WorkerWakeCheck:
    def __init__(self):
        self.boot_id = str(uuid4())
        self.checked: set[tuple[str, str]] = set()
        self.pending: dict[tuple[str, str], dict] = {}

    async def check(self, tools) -> None:
        scope = (str(tools.scope.organization_id), str(tools.scope.run_id))
        if scope in self.checked:
            return
        if scope in self.pending:
            await self._record(tools, scope, self.pending[scope])
            return
        snapshot = await tools.call("get_finance_snapshot", {})
        if (snapshot.get("organization", {}).get("id"), snapshot.get("run", {}).get("id")) != scope:
            raise FinanceError("worker_wake_snapshot_scope_mismatch")
        # No email addresses, source bodies or model output are copied into the
        # receipt. The actor still fetches current evidence through its own tools.
        summary = {
            "contract": "finance-worker-wake-v1",
            "boot_id": self.boot_id,
            "snapshot_at": snapshot.get("updated_at"),
            "run_revision": snapshot["run"].get("revision"),
            "position": snapshot.get("position", {}),
            "case_count": len(snapshot.get("cases", [])),
            "obligation_count": len(snapshot.get("obligations", [])),
            "pending_approval_count": sum(
                row.get("status") == "pending" for row in snapshot.get("approvals", [])
            ),
            "rejected_approval_count": sum(
                row.get("status") == "rejected" for row in snapshot.get("approvals", [])
            ),
            "mailbox_statuses": [
                row.get("status") for row in snapshot.get("connections", [])
                if row.get("provider") == "gmail"
            ],
            "coverage": "recorded_finance_state_only",
            "mail_discovery": "scheduled_label_polling_with_history_catchup",
            "meaning": "Worker inspected current recorded state; unknown cash and unimported evidence remain unknown. No financial action or reconciliation performed.",
        }
        self.pending[scope] = summary
        await self._record(tools, scope, summary)

    async def _record(self, tools, scope: tuple[str, str], summary: dict) -> None:
        await tools.call("record_trace", {
            "event_type": "worker_finance_wake",
            "payload": summary,
            "idempotency_key": "worker-wake:" + self.boot_id,
        })
        # A failed snapshot/receipt is retried on a later job, never marked checked.
        self.checked.add(scope)
        self.pending.pop(scope, None)

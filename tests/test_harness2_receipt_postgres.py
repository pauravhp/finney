"""Real PostgreSQL trace boundary + real upstream search; model/Storage fixtures."""
import copy

import psycopg
import pytest
from test_finance_postgres import database as database  # noqa: PLC0414
from test_finance_postgres import state as state  # noqa: PLC0414
from test_harness2_candidate import FixtureEditor, FixtureOpenCode, source_trace
from test_improvement_postgres import LocalPostgresWithFixtureArtifacts

from app.finance.tools import FinanceToolClient
from app.finance.types import Scope
from app.improvement.harness2_candidate import make_harness2_candidate_search
from app.runtime.jobs import DEFAULT_SKILL


class KernelSearchPort:
    def __init__(self, tools):
        self.tools, self.scope = tools, tools.scope
        self.saved, self.traces = [], []

    async def call(self, name, arguments):
        if name == "put_artifact":
            self.saved.append(copy.deepcopy(arguments))
        if name == "record_trace":
            self.traces.append(copy.deepcopy(arguments))
        return await self.tools.call(name, arguments)

    def for_evaluation(self, snapshot):
        return self.tools.for_evaluation(snapshot)


@pytest.mark.asyncio
async def test_actual_search_receipt_survives_required_kernel_key_and_replays_once(state):
    connection, organization, run, _users = state
    backend = LocalPostgresWithFixtureArtifacts(connection)
    tools = FinanceToolClient(Scope(organization, run), backend)
    # Reproduce the previous production failure against the actual guard. This
    # failed SQL statement never creates a search receipt or affects a model.
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="idempotency key required"):
        await tools.call("record_trace", {"event_type": "harness2_candidate_search", "payload": {}})
    port, editor = KernelSearchPort(tools), FixtureEditor()
    actor = FixtureOpenCode(port)
    result = await make_harness2_candidate_search(actor, editor)(
        trace=source_trace(), baseline_content=DEFAULT_SKILL.read_text(), tools=port,
        fixed_context=None, policy={}, reserve_calls=lambda _count: None, remaining_budget=94,
    )
    assert len(actor.calls) == 4 and len(editor.calls) == 4
    receipt = port.traces[-1]
    assert receipt["payload"]["search_artifact"] == result["generation"]["evidence"]["search_artifact"]
    assert receipt["idempotency_key"].endswith(receipt["payload"]["search_artifact"]["content_sha256"])
    first = await tools.call("record_trace", receipt)
    second = await tools.call("record_trace", receipt)
    assert first == second
    rows = connection.execute(
        "select id,payload from trace_events where organization_id=%s and run_id=%s and event_type='harness2_candidate_search'",
        (organization, run),
    ).fetchall()
    assert len(rows) == 1 and str(rows[0][0]) == first["id"]
    assert rows[0][1]["activation"] == "not_requested"
    assert connection.execute("select count(*) from promotions where run_id=%s", (run,)).fetchone()[0] == 0

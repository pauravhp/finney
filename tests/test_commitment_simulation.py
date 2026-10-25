"""Simulation semantics on the real Python/PostgreSQL finance kernels; no inference."""
from uuid import uuid4

import pytest
from test_finance_postgres import database as database  # noqa: PLC0414
from test_finance_postgres import identity
from test_finance_postgres import state as state  # noqa: PLC0414
from test_guided_scenario import create

from app.config import Settings
from app.finance.tools import FinanceToolClient
from app.finance.types import FinanceError, Scope
from app.guided_demo import seed_guided_scenario


@pytest.mark.asyncio
async def test_actual_amendment_changes_current_availability_without_double_counting(state):
    conn, db, tools, job, _scope = create(state)
    await seed_guided_scenario(Settings(_env_file=None), tools, db, job)
    run = tools.scope.run_id
    before = await tools.call("get_financial_position", {})
    assert before["cash_minor"] == "780000" and before["available_minor"] == "412000"

    # This legitimately models an ADDITIONAL $420, not replacing a recorded $480.
    hypothetical = await tools.call("simulate_commitment", {"amount_minor": 42000, "currency": "USD"})
    assert hypothetical["current_available_minor"] == "412000"
    assert hypothetical["additional_commitment_minor"] == "42000"
    assert hypothetical["available_after_minor"] == "370000"
    assert hypothetical["calculation"] == "current_available_minus_additional_commitment"
    assert hypothetical["is_projection"] and not hypothetical["effects_enabled"]
    assert hypothetical["position_basis"] == "recorded_position_at_read"
    assert await tools.call("get_financial_position", {}) == before

    conn.execute("reset role")
    av = conn.execute(
        "select to_jsonb(o) from obligations o where run_id=%s and title like 'Harbor AV%%'", (run,),
    ).fetchone()[0]
    current_source = conn.execute(
        "select id from source_items where run_id=%s and external_id like '%%:av' and version=2", (run,),
    ).fetchone()[0]
    identity(conn, service=True)
    changed = await tools.call("propose_obligation_update", {
        "id": av["id"], "expected_version": av["version"], "case_id": av["case_id"],
        "title": av["title"], "amount_minor": 42000, "currency": "USD", "direction": "payable",
        "source_refs": [{"id": str(current_source), "version": 2}],
        "idempotency_key": "simulation-semantics-real-amendment",
    })
    assert changed["version"] == 2
    # A fresh read, not either simulation, is the factual post-update position.
    after = await tools.call("get_financial_position", {})
    assert after["cash_minor"] == before["cash_minor"]
    assert after["committed_minor"] == "362000" and after["available_minor"] == "418000"
    after_simulation = await tools.call("simulate_commitment", {"amount_minor": 42000, "currency": "USD"})
    assert after_simulation["current_available_minor"] == "418000"
    assert after_simulation["available_after_minor"] == "376000"
    assert await tools.call("get_financial_position", {}) == after


@pytest.mark.asyncio
@pytest.mark.parametrize("available", [None, "0", "900"])
async def test_snapshot_simulation_preserves_unknown_and_zero_without_live_reads(available):
    scope = Scope(uuid4(), uuid4())
    class NoNetwork:
        async def rpc(self, *args):
            raise AssertionError("snapshot simulation must not read live state")
    snapshot = {"organization": {"id": str(scope.organization_id)}, "run": {"id": str(scope.run_id)},
                "position": {"currency": "USD", "available_minor": available}}
    tools = FinanceToolClient(scope, NoNetwork()).for_evaluation(snapshot)
    result = await tools.call("simulate_commitment", {"amount_minor": 100, "currency": "USD"})
    assert result["current_available_minor"] == available
    assert result["available_after_minor"] == (None if available is None else str(int(available) - 100))
    assert result["status"] == ("unknown_cash" if available is None else "simulation")
    assert result["position_basis"] == "captured_snapshot" and result["is_projection"]
    assert not result["effects_enabled"]
    assert (await tools.call("get_financial_position", {}))["available_minor"] == available
    with pytest.raises(FinanceError, match="currency"):
        await tools.call("simulate_commitment", {"amount_minor": 100, "currency": "CAD"})
    with pytest.raises(FinanceError):
        await tools.call("simulate_commitment", {"amount_minor": -100, "currency": "USD"})

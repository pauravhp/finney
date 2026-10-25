from uuid import uuid4

import pytest

from app.finance.tools import FinanceToolClient
from app.finance.types import (
    FinanceError,
    LedgerEntry,
    Scope,
    cash_forecast,
    minor_units,
    validate_postings,
)


@pytest.mark.parametrize("value", [1.2, True, "1.2", " 1", 9_000_000_000_000_000_001])
def test_reject_inexact_money(value):
    with pytest.raises(FinanceError):
        minor_units(value)


def test_balance_each_currency_separately():
    with pytest.raises(FinanceError, match="balanced"):
        validate_postings([LedgerEntry("cash", 100, "USD"), LedgerEntry("equity", -100, "EUR")])
    validate_postings([LedgerEntry("cash", 100, "USD"), LedgerEntry("equity", -100, "USD")])


def test_forecast_unknown_and_partial_settlement():
    obligations = [
        {"id": "later", "currency": "USD", "direction": "receivable", "amount_minor": "200", "due_date": "2026-10-29"},
        {"id": "first", "currency": "USD", "direction": "payable", "amount_minor": "300", "settled_minor": "100", "due_date": "2026-10-25"},
    ]
    assert cash_forecast(None, obligations, currency="USD")["projected_cash_minor"] is None
    result = cash_forecast(500, obligations, currency="USD")
    assert [r["projected_cash_minor"] for r in result["rows"]] == ["300", "500"]
    assert result["status"] == "projection"
    with pytest.raises(FinanceError, match="FX"):
        cash_forecast(0, obligations, currency="CAD")


class ForbiddenNetwork:
    """Explicit test double: evaluation must never read live finance state."""
    async def rpc(self, *args, **kwargs):
        raise AssertionError("unexpected live read")


@pytest.mark.asyncio
async def test_prepare_boundary_uses_frozen_snapshot_and_denies_effects():
    scope = Scope(uuid4(), uuid4())
    snapshot = {"organization": {"id": str(scope.organization_id)}, "run": {"id": str(scope.run_id)},
                "position": {"currency": "USD", "cash_minor": "200", "available_minor": "100"},
                "cases": [{"id": "case-1", "data": {"evidence": "original"}}], "source_items": [{"id": "s1", "version": 1}]}
    client = FinanceToolClient(scope, ForbiddenNetwork()).for_evaluation(snapshot)
    snapshot["cases"][0]["data"]["evidence"] = "mutated"
    assert (await client.call("get_case", {"case_id": "case-1"}))["data"]["evidence"] == "original"
    for operation in ["post_ledger", "create_approval_request", "reserve_approved_payment", "confirm_payment", "set_active_skill_version"]:
        with pytest.raises(FinanceError, match="prepare-only"):
            await client.call(operation, {})
    with pytest.raises(FinanceError, match="identity"):
        await client.call("get_case", {"run_id": str(uuid4())})
    valid = await client.call("validate_prepared_decision", {"decision": {"action": "reimburse_organizer", "amount_minor": "100", "currency": "USD", "evidence_refs": [{"id": "s1", "version": 1}]}})
    assert valid["valid"] and not valid["effects_enabled"]
    stale = await client.call("validate_prepared_decision", {"decision": {"action": "pay_vendor", "amount_minor": "100", "currency": "USD", "evidence_refs": [{"id": "s1", "version": 2}]}})
    assert not stale["hard_invariants_passed"]


def test_snapshot_scope_cannot_be_rebound():
    with pytest.raises(FinanceError, match="scope"):
        FinanceToolClient(Scope(uuid4(), uuid4()), ForbiddenNetwork()).for_evaluation({"run": {"id": str(uuid4())}})

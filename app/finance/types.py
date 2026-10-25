from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

MAX_MINOR = 9_000_000_000_000_000_000


class FinanceError(ValueError):
    pass


def minor_units(value: Any, *, nonnegative: bool = False) -> int:
    """Reject float/bool coercion and out-of-range database integers."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise FinanceError("amount must be integer minor/base units")
    if isinstance(value, str) and (not value or value.strip() != value or not value.lstrip("-").isdigit()):
        raise FinanceError("amount must be a decimal integer string")
    result = int(value)
    if abs(result) > MAX_MINOR or (nonnegative and result < 0):
        raise FinanceError("amount out of range")
    return result


@dataclass(frozen=True)
class Scope:
    organization_id: UUID
    run_id: UUID
    actor_id: UUID | None = None

    def params(self) -> dict[str, str]:
        return {"p_organization_id": str(self.organization_id), "p_run_id": str(self.run_id)}


@dataclass(frozen=True)
class LedgerEntry:
    account: str
    amount_minor: int
    currency: str


def validate_postings(entries: list[LedgerEntry]) -> None:
    if len(entries) < 2:
        raise FinanceError("a journal requires at least two postings")
    totals: dict[str, int] = {}
    for entry in entries:
        amount = minor_units(entry.amount_minor)
        if not entry.account or not entry.currency or amount == 0:
            raise FinanceError("postings require account, currency and nonzero amount")
        totals[entry.currency] = totals.get(entry.currency, 0) + amount
    if any(totals.values()):
        raise FinanceError("journal is not balanced per currency")


def cash_forecast(opening_minor: int | None, obligations: list[dict[str, Any]], *, currency: str) -> dict[str, Any]:
    """A forecast is a projection, never evidence that receivables have settled."""
    opening = None if opening_minor is None else minor_units(opening_minor)
    balances = opening
    rows = []
    for item in sorted(obligations, key=lambda row: (row.get("due_date") or "9999-12-31", str(row.get("id", "")))):
        if item.get("currency") != currency:
            raise FinanceError("cross-currency forecast requires an explicit FX conversion")
        if item.get("status") in {"settled", "cancelled"}:
            continue
        amount = minor_units(item["amount_minor"], nonnegative=True) - minor_units(item.get("settled_minor", 0), nonnegative=True)
        if amount < 0 or item.get("direction") not in {"payable", "receivable"}:
            raise FinanceError("invalid obligation")
        due = item.get("due_date")
        if due:
            date.fromisoformat(due)
        delta = amount if item["direction"] == "receivable" else -amount
        if balances is not None:
            balances += delta
        rows.append({"obligation_id": item.get("id"), "due_date": due, "delta_minor": str(delta),
                     "projected_cash_minor": None if balances is None else str(balances),
                     "evidence_status": item.get("evidence_status", "unknown")})
    return {"currency": currency, "opening_minor": None if opening is None else str(opening),
            "projected_cash_minor": None if balances is None else str(balances), "rows": rows,
            "status": "unknown_opening" if opening is None else "projection"}

import csv
import hashlib
import io
from datetime import date
from decimal import Decimal, InvalidOperation


def parse_finance_csv(content: str, *, currency: str, decimal_places: int = 2) -> list[dict]:
    """Validate every row before returning any import; no automatic settlement claim."""
    if len(currency) != 3 or not currency.isalpha() or currency != currency.upper():
        raise ValueError("Use an explicit uppercase ISO currency code")
    if decimal_places not in range(9):
        raise ValueError("Invalid currency decimal precision")
    reader = csv.DictReader(io.StringIO(content))
    required = {"reference", "date", "description", "amount", "kind"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("CSV needs reference,date,description,amount,kind columns")
    seen: set[str] = set()
    records = []
    for line, row in enumerate(reader, 2):
        reference = row["reference"].strip()
        if not reference or reference in seen:
            raise ValueError(f"CSV row {line}: missing or duplicate reference")
        if row["kind"] not in {"opening_balance", "expense", "receivable", "commitment", "payment"}:
            raise ValueError(f"CSV row {line}: unsupported record kind")
        try:
            occurred_on = date.fromisoformat(row["date"]).isoformat()
            value = Decimal(row["amount"])
            minor = value * (10**decimal_places)
            if (
                not value.is_finite()
                or minor != minor.to_integral_value()
                or abs(minor) > 2**63 - 1
            ):
                raise ValueError()
        except (ValueError, InvalidOperation) as exc:
            raise ValueError(f"CSV row {line}: invalid date or exact monetary amount") from exc
        seen.add(reference)
        records.append(
            {
                "provider": "csv",
                "external_id": reference,
                "kind": row["kind"],
                "occurred_on": occurred_on,
                "description": row["description"],
                "amount_minor": str(int(minor)),
                "currency": currency,
                "evidence_state": "reported",
                "content_hash": hashlib.sha256(repr(sorted(row.items())).encode()).hexdigest(),
            }
        )
    return records

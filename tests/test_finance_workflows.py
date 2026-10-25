"""Domain and coordinator tests. Provider/storage fixtures are explicit; no live calls."""
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.finance.types import FinanceError, Scope
from app.finance.workflows import (
    build_close_report,
    ingest_uploaded_document,
    manual_evidence,
    persist_director_message,
    queue_automatic_improvement,
)


def test_manual_entries_are_reported_not_cash_even_with_extra_claims():
    payload = {"description": "Food deposit", "currency": "USD", "amount_minor": "120000", "direction": "payable", "evidence_status": "provider_confirmed", "paid": True}
    evidence = manual_evidence(payload, {"id": str(uuid4()), "requested_by": str(uuid4())})
    assert evidence["evidence_state"] == "reported"
    assert evidence["amount_minor"] == "120000"
    assert "paid" not in evidence and "evidence_status" not in evidence
    for invalid in [1.25, True, "1.25", "-1"]:
        with pytest.raises(FinanceError):
            manual_evidence({**payload, "amount_minor": invalid}, {"id": str(uuid4())})


def test_close_pack_keeps_promised_income_and_partial_payments_distinct():
    snapshot = {"run": {"revision": 7}, "position": {"cash_minor": None, "reconciled_at": None},
                "cases": [{"id": "case", "title": "Missing receipt", "status": "open", "data": {"finding": "Ask organizer"}}], "approvals": []}
    obligations = [
        {"currency": "USD", "status": "open", "direction": "receivable", "amount_minor": "1000000", "settled_minor": "0"},
        {"currency": "USD", "status": "open", "direction": "payable", "amount_minor": "100000", "settled_minor": "20000"},
        {"currency": "CAD", "status": "settled", "direction": "payable", "amount_minor": "500", "settled_minor": "500"},
        {"currency": "USD", "status": "cancelled", "direction": "payable", "amount_minor": "999999", "settled_minor": "0"},
    ]
    report = build_close_report(snapshot, obligations, cutoff="2026-10-25T00:00:00Z")
    assert report["totals_by_currency"]["USD"] == {"payable_minor": "80000", "paid_minor": "20000", "receivable_minor": "1000000", "received_minor": "0"}
    assert report["totals_by_currency"]["CAD"]["paid_minor"] == "500"
    assert report["position"]["cash_minor"] is None
    assert report["reconciliation"]["status"] == "not_reconciled"
    assert report["handover"][0]["case_id"] == "case"
    with pytest.raises(FinanceError, match="settlement_exceeds"):
        build_close_report(snapshot, [{**obligations[0], "settled_minor": "1000001"}], cutoff="now")


@pytest.mark.asyncio
async def test_cross_run_upload_denied_before_storage_download():
    scope = Scope(uuid4(), uuid4())
    tools = AsyncMock(scope=scope)
    db = AsyncMock()
    db.select.return_value = [{"role": "director"}]
    job = {"organization_id": str(scope.organization_id), "run_id": str(scope.run_id), "requested_by": str(uuid4())}
    with pytest.raises(FinanceError, match="upload_artifact_scope_invalid"):
        await ingest_uploaded_document(None, tools, db, {"artifact_path": f"{scope.organization_id}/{uuid4()}/uploads/{uuid4()}"}, job)
    db.download.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_improvement_retry_reuses_exact_job_not_a_second_budget():
    job = {"id": str(uuid4()), "organization_id": str(uuid4()), "run_id": str(uuid4()), "requested_by": str(uuid4()), "command_type": "review_case"}
    outcome = {"status": "completed", "triage": {"status": "completed"}, "trace": {"id": str(uuid4())}}
    db = AsyncMock()
    rows = []
    async def select(*args, **kwargs):
        return rows
    async def insert(table, row):
        rows.append({"id": str(uuid4()), **row})
        return rows
    db.select.side_effect = select
    db.insert.side_effect = insert
    first = await queue_automatic_improvement(db, job, outcome)
    second = await queue_automatic_improvement(db, job, outcome)
    assert first["job_id"] == second["job_id"]
    assert db.insert.await_count == 1


@pytest.mark.asyncio
async def test_director_question_preserves_closed_financial_case_and_finding():
    case_id, old_source, new_source = (str(uuid4()) for _ in range(3))
    prior = {"id": case_id, "version": 3, "title": "A settled expense", "status": "closed",
             "data": {"source_ids": [old_source], "finding": {"decision": "already_settled"}}}
    tools, db = AsyncMock(), AsyncMock()
    db.select.return_value = [{"role": "director"}]
    writes = []
    async def call(name, args):
        if name == "put_artifact": return {"artifact_path": "unit-private-artifact"}
        if name == "record_source": return {"id": new_source}
        if name == "get_case": return prior
        if name == "record_case":
            writes.append(args)
            return {"id": case_id}
        raise AssertionError(name)
    tools.call.side_effect = call
    job = {"id": str(uuid4()), "organization_id": str(uuid4()), "run_id": str(uuid4()),
           "requested_by": str(uuid4()), "payload": {"case_id": case_id, "message": "Why was this closed?"}}
    await persist_director_message(tools, db, job)
    assert writes[0]["status"] == "closed"
    assert writes[0]["data"]["finding"] == prior["data"]["finding"]
    assert writes[0]["data"]["source_ids"] == [old_source, new_source]

"""Trusted intake, decision coordination and evidence-based close reports."""
from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID

from app.finance.types import FinanceError, minor_units
from app.storage.supabase import SupabaseError


def manual_evidence(payload: dict, job: dict) -> dict:
    description = payload.get("description")
    currency = payload.get("currency")
    direction = payload.get("direction")
    if (
        not isinstance(description, str) or not 1 <= len(description.strip()) <= 4000
        or not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency)
        or direction not in {"payable", "receivable"}
    ):
        raise FinanceError("manual_entry_needs_description_currency_and_direction")
    return {
        "provider": "manual",
        "external_id": str(UUID(job["id"])),
        "description": description.strip(),
        "amount_minor": str(minor_units(payload.get("amount_minor"), nonnegative=True)),
        "currency": currency,
        "direction": direction,
        "submitted_by": job.get("requested_by"),
        "evidence_state": "reported",
        "meaning": "User-reported obligation for review; not payment or receipt confirmation",
    }


async def require_event_editor(db, job: dict) -> None:
    if not job.get("requested_by"):
        raise FinanceError("authenticated_event_editor_required")
    members = await db.select("memberships", filters={
        "organization_id": "eq." + job["organization_id"],
        "user_id": "eq." + job["requested_by"], "active": "eq.true",
        "role": "in.(director,finance)",
    }, limit=1)
    if not members:
        raise FinanceError("event_editor_authority_changed")


async def ingest_uploaded_document(settings, tools, db, payload: dict, job: dict) -> dict:
    from app.documents import ClaudeVisionOCR, DocumentService
    from app.models.providers import ModelConfig

    await require_event_editor(db, job)
    prefix = f"{tools.scope.organization_id}/{tools.scope.run_id}/uploads/"
    path = payload.get("artifact_path", "")
    if not isinstance(path, str) or not path.startswith(prefix) or not re.fullmatch(r"[a-f0-9-]{36}", path.removeprefix(prefix)):
        raise FinanceError("upload_artifact_scope_invalid")
    filename = payload.get("filename", "document")
    if not isinstance(filename, str) or not 1 <= len(filename) <= 200:
        raise FinanceError("upload_filename_invalid")
    raw = await db.download("finance-artifacts", path)
    if len(raw) > 3 * 1024 * 1024 or len(raw) != payload.get("size"):
        raise FinanceError("upload_size_invalid")
    documents = DocumentService(tools, db, ocr=ClaudeVisionOCR(ModelConfig.from_settings(settings)))
    result = await documents.ingest(raw, filename=filename, content_type=payload.get("content_type", ""), external_id="upload:" + path)
    cases = await db.select("cases", filters={
        "organization_id": "eq." + job["organization_id"], "run_id": "eq." + job["run_id"],
        "data->>uploaded_source_id": "eq." + result["source_id"],
    }, limit=1)
    if cases:
        case = cases[0]
    else:
        case = await tools.call("record_case", {
            "title": filename, "status": "open",
            "data": {"source_ids": [result["source_id"]], "source_refs": [result["source_ref"]],
                     "uploaded_source_id": result["source_id"], "extraction_status": result["extraction_status"],
                     "evidence_state": "reported"},
            "idempotency_key": "upload-case:" + result["source_id"],
        })
    return {**result, "case_id": case["id"]}


async def persist_director_message(tools, db, job: dict) -> dict:
    await require_event_editor(db, job)
    payload = job["payload"]
    message = payload.get("message")
    if not isinstance(message, str) or not 1 <= len(message.strip()) <= 4000:
        raise FinanceError("director_message_required")
    content = json.dumps({"message": message, "submitted_by": job["requested_by"],
                          "meaning": "Director request; does not grant payment approval"}, sort_keys=True)
    artifact = await tools.call("put_artifact", {"name": "director-message.json", "content": content, "content_type": "application/json"})
    source = await tools.call("record_source", {
        "external_id": "director-message:" + job["id"], "version": 1, "source_type": "director_message",
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(), "artifact_path": artifact["artifact_path"],
        "metadata": {"submitted_by": job["requested_by"], "evidence_state": "reported"},
        "idempotency_key": "director-message-source:" + job["id"],
    })
    prior = await tools.call("get_case", {"case_id": payload["case_id"]}) if payload.get("case_id") else None
    if prior and source["id"] in prior.get("data", {}).get("source_ids", []):
        return {"case_id": prior["id"], "source_id": source["id"]}
    data = dict(prior.get("data", {})) if prior else {}
    data["source_ids"] = [*data.get("source_ids", []), source["id"]]
    data["director_request"] = message
    data["evidence_state"] = "reported"
    args = {"title": prior["title"] if prior else message[:100], "status": prior["status"] if prior else "open", "data": data,
            "idempotency_key": "director-message-case:" + job["id"]}
    if prior:
        args.update(id=prior["id"], expected_version=prior["version"])
    case = await tools.call("record_case", args)
    return {"case_id": case["id"], "source_id": source["id"]}


async def queue_automatic_improvement(db, job: dict, outcome: dict) -> dict:
    from app.improvement.fresh import FRESH_SUITE_ID
    from app.runtime.jobs import automatic_improvement_request

    request = automatic_improvement_request(job, outcome, suite_id=FRESH_SUITE_ID)
    if request is None:
        return {"status": "not_requested"}
    filters = {"organization_id": "eq." + job["organization_id"], "run_id": "eq." + job["run_id"],
               "idempotency_key": "eq." + request["idempotency_key"]}
    rows = await db.select("jobs", filters=filters, limit=1)
    if not rows:
        try:
            rows = await db.insert("jobs", {"organization_id": job["organization_id"], "run_id": job["run_id"],
                "command_type": "evaluate_improvement", "requested_by": job.get("requested_by"), **request})
        except SupabaseError as error:
            if error.status != 409:
                raise
            rows = await db.select("jobs", filters=filters, limit=1)
    if len(rows) != 1 or rows[0]["payload"] != request["payload"]:
        raise FinanceError("improvement_queue_idempotency_conflict")
    return {"status": "queued", "job_id": rows[0]["id"], "meaning": "Bounded diagnosis requested; no improvement or promotion claimed"}


def build_close_report(snapshot: dict, obligations: list, *, cutoff: str) -> dict:
    """Totals derive from recorded obligations, with unknown reconciliation explicit."""
    currencies: dict[str, dict] = {}
    for obligation in obligations:
        if obligation["status"] == "cancelled":
            continue
        totals = currencies.setdefault(obligation["currency"], {"payable_minor": 0, "paid_minor": 0, "receivable_minor": 0, "received_minor": 0})
        amount = minor_units(obligation["amount_minor"], nonnegative=True)
        settled = minor_units(obligation["settled_minor"], nonnegative=True)
        if settled > amount:
            raise FinanceError("settlement_exceeds_obligation")
        side = "payable_minor" if obligation["direction"] == "payable" else "receivable_minor"
        totals[side] += amount - settled
        totals["paid_minor" if side == "payable_minor" else "received_minor"] += settled
    return {
        "audience": "directors_and_event_handover", "cutoff": cutoff,
        "run_revision": snapshot["run"]["revision"], "position": snapshot["position"],
        "totals_by_currency": {currency: {key: str(value) for key, value in totals.items()} for currency, totals in currencies.items()},
        "budget": snapshot.get("budget", {"lines": [], "decisions": []}),
        "obligations": obligations, "sources": snapshot.get("source_items", []),
        "cases": snapshot["cases"], "approvals": snapshot["approvals"],
        "handover": [{"case_id": case["id"], "title": case["title"], "status": case["status"],
                      "finding": case.get("data", {}).get("finding")} for case in snapshot["cases"] if case["status"] not in {"closed", "resolved"}],
        "reconciliation": {"status": "recorded" if snapshot["position"].get("reconciled_at") else "not_reconciled",
                           "as_of": snapshot["position"].get("reconciled_at")},
        "basis": "Recorded evidence. Budget allocations do not establish cash. Promised sponsorship is not received cash. Unsettled and unverified items remain open.",
        "limitations": ["No tax filing or tax classification performed", "No bank connection; completeness depends on provided evidence", "Sponsor-specific disclosure review is required before sharing this internal report"],
    }

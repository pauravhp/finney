"""A small immutable synthetic corpus; all resulting reviews use the real actor.

Seeding creates source documents and open cases, never financial effects or
model outputs. The trusted dispatcher owns queue insertion after this returns.
"""

from __future__ import annotations

import copy
import hashlib
import json
from uuid import UUID

from app.config import Settings
from app.connectors.intake import persist_evidence
from app.finance.tools import FinanceToolClient
from app.finance.types import FinanceError
from app.storage.supabase import SupabaseClient

# Persisted bundle identifier; keep its legacy spelling for stored-run compatibility.
DEMO_BUNDLE_VERSION = "finny-guided-sources-v1"
_DOCUMENTS = (
    {
        "external_id": DEMO_BUNDLE_VERSION + ":organizer-purchase",
        "description": "SYNTHETIC demo: organizer purchase receipt and personal-card note",
        "headers": {"subject": "SYNTHETIC demo: organizer purchase receipt and personal-card note"},
        "currency": "USD",
        "documents": [
            {
                "kind": "supplier_receipt",
                "text": "SYNTHETIC DOCUMENT. Pine Market receipt PM-DEMO-71: event food, total USD 87.00, paid by card ending 1234. Supplier remaining balance USD 0.00.",
            },
            {
                "kind": "organizer_note",
                "text": "SYNTHETIC DOCUMENT. Organizer Mira: Card ending 1234 is my personal card. I paid PM-DEMO-71 and have not received money back from the event. I am asking the director about repayment. No recipient payment address or bank record is included.",
            },
        ],
    },
    {
        "external_id": DEMO_BUNDLE_VERSION + ":sponsor-commitment",
        "description": "SYNTHETIC demo: sponsor commitment and payment-timing note",
        "headers": {"subject": "SYNTHETIC demo: sponsor commitment and payment-timing note"},
        "currency": "USD",
        "documents": [
            {
                "kind": "sponsor_commitment",
                "text": "SYNTHETIC DOCUMENT. North Star Labs sponsorship commitment NS-DEMO-22: USD 2,500.00 for the event. Payment due November 1, 2026. Event and sponsor representatives signed this synthetic commitment.",
            },
            {
                "kind": "sponsor_message",
                "text": "SYNTHETIC DOCUMENT. North Star Labs representative: We have not sent the USD 2,500.00 contribution yet. We plan to send it by the stated due date. This message has no attached payment receipt.",
            },
        ],
    },
)


def demo_source_bundle() -> tuple[dict, ...]:
    """Return detached documents so a caller cannot mutate the shared seed."""
    return tuple(
        {
            "provider": "demo_bundle",
            "input_kind": "explicit_synthetic_documents",
            "synthetic": True,
            **copy.deepcopy(document),
        }
        for document in _DOCUMENTS
    )


def _digest(evidence: dict) -> str:
    return hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()


async def seed_demo_bundle(
    settings: Settings, tools: FinanceToolClient, db: SupabaseClient, job: dict
) -> dict:
    """Validate actual owned demo, preserve prior edits, persist two real sources.

    No model/provider invocation occurs here. Queue ``source_results`` whose
    ``review_required`` is true with the returned stable ``review_key`` before
    marking the trusted intake job complete; existing queue idempotency applies.
    """
    del settings  # Corpus and permission checks have no environment/credential fallback.
    if getattr(tools, "prepare_only", False):
        raise FinanceError("evaluation_cannot_seed_demo")
    try:
        organization, run = UUID(str(job["organization_id"])), UUID(str(job["run_id"]))
        owner = UUID(str(job["requested_by"]))
        UUID(str(job["id"]))
    except (KeyError, TypeError, ValueError):
        raise FinanceError("authenticated_scoped_demo_job_required") from None
    if organization != tools.scope.organization_id or run != tools.scope.run_id:
        raise FinanceError("demo_job_scope_mismatch")
    if job.get("command_type") != "intake":
        raise FinanceError("demo_seed_requires_intake_job")
    payload = job.get("payload", {})
    if (
        not isinstance(payload, dict)
        or set(payload) - {"source", "bundle_version"}
        or (
            payload.get("source") != "demo_bundle"
            or payload.get("bundle_version", DEMO_BUNDLE_VERSION) != DEMO_BUNDLE_VERSION
        )
    ):
        raise FinanceError("demo_bundle_payload_invalid")
    scope = {"organization_id": "eq." + str(organization), "run_id": "eq." + str(run)}
    results = []
    for evidence in demo_source_bundle():
        # Recheck current ownership/active run before each independent storage unit.
        await db.rpc(
            "assert_finance_demo_owner",
            {
                "p_organization_id": str(organization),
                "p_run_id": str(run),
                "p_actor_id": str(owner),
            },
        )
        external = "demo_bundle:" + evidence["external_id"]
        existing_cases = await db.select(
            "cases", filters={**scope, "data->>source_external_id": "eq." + external}, limit=1
        )
        if existing_cases:
            case = existing_cases[0]
            sources = await db.select(
                "source_items",
                filters={**scope, "external_id": "eq." + external, "order": "version.desc"},
                limit=1,
            )
            if not sources:
                raise FinanceError("demo_existing_case_source_missing")
            source = sources[0]
            untouched = (
                case.get("version") == 1
                and case.get("status") == "open"
                and case.get("title") == evidence["description"]
                and case.get("data", {}).get("source_ids") == [source["id"]]
                and "finding" not in case.get("data", {})
                and source.get("content_sha256") == _digest(evidence)
            )
            recorded = {
                "source_id": source["id"],
                "source_ref": {"id": source["id"], "version": source["version"]},
                "case_id": case["id"],
                "status": "unchanged" if untouched else "preserved",
                "review_required": untouched,
            }
        else:
            recorded = {**await persist_evidence(tools, db, evidence), "review_required": True}
        results.append({**recorded, "review_key": evidence["external_id"], "synthetic": True})
    manifest = {
        "bundle_version": DEMO_BUNDLE_VERSION,
        "synthetic": True,
        "source_content_sha256": [_digest(evidence) for evidence in demo_source_bundle()],
    }
    await tools.call(
        "record_trace",
        {
            "event_type": "demo_bundle_seeded",
            "payload": manifest,
            "idempotency_key": "demo-bundle:" + DEMO_BUNDLE_VERSION,
        },
    )
    return {
        "status": "completed",
        "bundle_version": DEMO_BUNDLE_VERSION,
        "synthetic": True,
        "bundle_sha256": _digest(manifest),
        "source_results": results,
        "suggested_prompts": [
            "Review the organizer purchase documents and explain what is supported and what still needs a human decision.",
            "Summarize the sponsor commitment, payment timing and the evidence of money received.",
            "What can we responsibly allocate to food while the sponsor contribution is pending and no opening bank statement is loaded?",
        ],
        "cash_established_by_seed": False,
        "payments_enabled": False,
        "meaning": "Synthetic source inputs and real review work; no model outcome or learning success is seeded.",
    }

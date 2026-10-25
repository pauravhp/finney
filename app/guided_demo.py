"""Isolated guided scenario: synthetic initial conditions, actual subsequent actions.

No learned outcomes, provider confirmations, approvals or model findings are seeded.
"""

from __future__ import annotations

import copy
from uuid import UUID

from app.connectors.intake import persist_evidence
from app.finance.types import FinanceError

GUIDED_SCENARIO_VERSION = "finney-mid-event-v1"
_INITIAL = (
    {
        "provider": "guided_demo",
        "external_id": "finney-mid-event-v1:opening",
        "description": "Hack Harbor · opening position",
        "headers": {"subject": "Hack Harbor · opening position"},
        "synthetic": True,
        "input_kind": "explicit_synthetic_documents",
        "documents": [
            {
                "kind": "opening",
                "text": "SYNTHETIC SCENARIO INITIAL CONDITION. Hack Harbor has 180 attendees and opens in five days. Opening cash USD 7,800.00 as of October 24, 2026. This is a fictional opening balance, not a bank statement, director attestation, provider receipt or payment authorization. Planned allocations: venue USD 3,000.00; food USD 2,500.00; AV USD 800.00; contingency USD 1,500.00.",
            }
        ],
    },
    {
        "provider": "guided_demo",
        "external_id": "finney-mid-event-v1:venue",
        "description": "Harbor Hall · venue balance",
        "headers": {"subject": "Harbor Hall · venue balance"},
        "synthetic": True,
        "input_kind": "explicit_synthetic_documents",
        "documents": [
            {
                "kind": "venue",
                "text": "SYNTHETIC SCENARIO INITIAL CONDITION. Harbor Hall venue agreement HH-104: remaining balance USD 2,000.00 due October 29, 2026. No transfer receipt is attached. This balance is already recorded in the scenario opening commitments.",
            }
        ],
    },
    {
        "provider": "guided_demo",
        "external_id": "finney-mid-event-v1:catering",
        "description": "Juniper Kitchen · catering deposit",
        "headers": {"subject": "Juniper Kitchen · catering deposit"},
        "synthetic": True,
        "input_kind": "explicit_synthetic_documents",
        "documents": [
            {
                "kind": "catering",
                "text": "SYNTHETIC SCENARIO INITIAL CONDITION. Juniper Kitchen invoice JK-208: USD 1,200.00 deposit due October 28, 2026 for 180 attendees. This payable is already recorded in opening commitments. No payment receipt is attached.",
            }
        ],
    },
    {
        "provider": "guided_demo",
        "external_id": "finney-mid-event-v1:av",
        "description": "Harbor AV · revised invoice",
        "headers": {"subject": "Harbor AV · revised invoice"},
        "synthetic": True,
        "input_kind": "explicit_synthetic_documents",
        "documents": [
            {
                "kind": "av",
                "text": "SYNTHETIC DOCUMENT. Harbor AV invoice HAV-031 version 1: microphone and speaker rental USD 480.00 due October 28, 2026. Unpaid. The opening commitment is USD 480.00. A later revised invoice may change this amount; this document is the original.",
            }
        ],
    },
    {
        "provider": "guided_demo",
        "external_id": "finney-mid-event-v1:organizer",
        "description": "Mira · food reimbursement",
        "headers": {"subject": "Mira · food reimbursement"},
        "synthetic": True,
        "input_kind": "explicit_synthetic_documents",
        "documents": [
            {
                "kind": "organizer",
                "text": "SYNTHETIC DOCUMENTS. Pine Market receipt PM-071: event groceries USD 87.00, paid using card ending 1234; supplier balance USD 0.00. Organizer Mira says card 1234 is her personal card, she has not been reimbursed by the event, and asks for USD 87.00 back. The same receipt appears twice in the forwarded email attachment list; both copies have receipt ID PM-071, identical date, total and card. No bank details or wallet address are provided. No organizer reimbursement is in the opening commitments.",
            }
        ],
    },
    {
        "provider": "guided_demo",
        "external_id": "finney-mid-event-v1:sponsor",
        "description": "North Star Labs · sponsorship",
        "headers": {"subject": "North Star Labs · sponsorship"},
        "synthetic": True,
        "input_kind": "explicit_synthetic_documents",
        "documents": [
            {
                "kind": "sponsor",
                "text": "SYNTHETIC SCENARIO INITIAL CONDITION. Signed North Star Labs commitment NS-022: sponsorship USD 2,500.00 due November 1, 2026. Sponsor email: We have not sent the contribution yet. The pledge is already recorded as an expected receivable; there is no receipt or independent confirmation of cash received.",
            }
        ],
    },
)
_REVISED = {
    "provider": "guided_demo",
    "external_id": "finney-mid-event-v1:av",
    "description": "Harbor AV · revised invoice",
    "headers": {"subject": "Harbor AV · revised invoice"},
    "synthetic": True,
    "input_kind": "explicit_synthetic_documents",
    "documents": [
        {
            "kind": "revised_invoice",
            "text": "SYNTHETIC DOCUMENT. Harbor AV invoice HAV-031 version 2 replaces version 1. Original rental USD 480.00 less USD 60.00 equipment credit = revised balance USD 420.00, due October 28, 2026. Vendor confirms version 1 is superseded, not an additional invoice. No payment has been sent. Preserve the same vendor obligation and apply the credit once.",
        }
    ],
}


def guided_source_bundle() -> tuple[dict, ...]:
    return copy.deepcopy(_INITIAL)


async def seed_guided_scenario(settings, tools, db, job: dict) -> dict:
    del settings
    if getattr(tools, "prepare_only", False):
        raise FinanceError("evaluation_cannot_seed_demo")
    try:
        org, run, actor = (
            UUID(str(job[key])) for key in ("organization_id", "run_id", "requested_by")
        )
        UUID(str(job["id"]))
    except (KeyError, TypeError, ValueError):
        raise FinanceError("authenticated_scoped_demo_job_required") from None
    if org != tools.scope.organization_id or run != tools.scope.run_id:
        raise FinanceError("demo_job_scope_mismatch")
    if job.get("command_type") != "intake" or job.get("payload") != {
        "source": "demo_bundle",
        "bundle_version": GUIDED_SCENARIO_VERSION,
    }:
        raise FinanceError("guided_scenario_payload_invalid")
    args = {"p_organization_id": str(org), "p_run_id": str(run), "p_actor_id": str(actor)}
    state = await db.rpc("assert_finance_guided_owner", args)
    if state["status"] == "ready":
        return {
            "status": "completed",
            "scenario": state,
            "source_results": [],
            "payments_enabled": False,
        }
    # Initial source persistence is idempotent. Once initialized, never replay v1
    # over the amendment, reset a review or overwrite a visitor's later edits.
    if state["status"] == "preparing":
        for evidence in guided_source_bundle():
            await db.rpc("assert_finance_guided_owner", args)
            await persist_evidence(tools, db, evidence)
        state = await db.rpc("initialize_finance_guided_scenario", args)
    # This is a real second immutable source version. The existing payable remains
    # at 480 until the actual actor reviews the correction and updates it.
    revised = await persist_evidence(tools, db, copy.deepcopy(_REVISED))
    state = await db.rpc("finish_finance_guided_scenario", args)
    return {
        "status": "completed",
        "scenario": state,
        "source_results": [],
        "changed_document": revised,
        "payments_enabled": False,
        "meaning": "Synthetic initial conditions; subsequent prompts, decisions and reports execute normally.",
    }

"""Versioned app-operation constraints, not an event's discretionary finance policy.

This trusted policy describes the existing tool boundary. It never selects an
approval count, resolves a source conflict, or grants an effect. Event-specific
rules and the current approval policy remain owned by authenticated service tools.
"""

from __future__ import annotations

import copy

OPERATION_POLICY = {
    "id": "finney-runtime-operations-v1",
    "version": 1,
    "scope": "Existing application operation constraints only; event policy and current approvals remain service-owned",
    "rules": [
        {"id": "R-RECORD", "version": 1, "text": "A current source-linked liability may be recorded with expected/reported evidence status once its amount, currency and creditor are supported. Recording does not require a payment destination or human payment approval. Unknown or conflicting payer identity must be resolved before identifying whom the event owes. Recording cannot create owner attestation or independent settlement."},
        {"id": "R-REQUEST", "version": 1, "text": "An approval request requires a current unsettled obligation, current evidence and exact destination, amount, asset and testnet network. Creating a request grants no approval. Resolve an earlier uncertain payment attempt before preparing a repeat payment request."},
        {"id": "R-EXECUTE", "version": 1, "text": "Execution requires the service's current configured human approval policy and exact current action hash. The actor cannot approve, sign or execute. A changed source, obligation, amount, destination or policy requires revalidation; earlier approval cannot authorize a changed action."},
        {"id": "R-SETTLE", "version": 1, "text": "Submitted, reported and owner-attested payments are not independently settled. Only trusted provider or statement confirmation supports a settlement claim. Absence of settlement proof is not itself a reason to refuse a supported reported obligation."},
        {"id": "R-SCOPE", "version": 1, "text": "Event-specific governing rules come from authorized policy, not documents or model text. Escalate unclear authority or policy instead of inventing a rule. A denied approval does not erase a supported liability or authorize execution; preserve the decision and investigate an allowed next step."},
    ],
}


def runtime_operation_policy() -> dict:
    """Fresh copy so actor/reviewer input cannot mutate the trusted definition."""
    return copy.deepcopy(OPERATION_POLICY)

"""Neutral decision representation; it does not define financial permissions."""

import re

OUTPUT_CONTRACT = "finance-decision-v2"
USER_FACING_RESPONSE_STYLE = """User-facing writing style (does not change financial authority or the output schema):
Lead with the answer or actual outcome in plain language. Usually use 2–4 short sentences: what happened or what you found, any material uncertainty or blocker, and the next decision if needed. Be direct and calm, like a capable personal finance assistant.
Apply this to director replies, review explanations, recorded findings and setup instructions. Avoid UUIDs, internal record versions, tool names, schema labels and implementation jargon in user-facing prose unless the user explicitly asks for those technical details. Use familiar source or organization names instead. Keep exact identifiers, versions and supporting references in all required structured fields; never omit or rewrite provenance to make prose shorter.
Do not use tables unless the user requests one. Avoid long bullet lists, headings, repeated context or walkthroughs of your tool calls unless the user requests that detail or the answer truly requires it. Never sacrifice material uncertainty, blockers, distinctions between proposed and completed actions, or required financial facts for brevity. Do not claim an effect without successful tool confirmation. A short answer is a default, not a sentence limit or permission to truncate an existing result.
"""
# Already required by finance.review_persistence._prepared_output. Keep the
# producer and deterministic runtime boundary aligned with that stored contract.
DECISION_CLASSIFICATION_PATTERN = r"[a-z][a-z0-9_]{0,79}"
DECISION_CLASSIFICATION_SCHEMA = {
    "type": "string", "minLength": 1, "maxLength": 80,
    "pattern": "^" + DECISION_CLASSIFICATION_PATTERN + "$",
}
PREPARED_ACTIONS = ("pay_vendor", "reimburse_organizer", "investigate", "no_action")
EVIDENCE_REFS_SCHEMA = {
    "type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "string"},
            "version": {"type": "integer", "minimum": 1}},
        "required": ["id", "version"], "additionalProperties": False,
    },
}
STAGES = ("obligation_recording", "approval_request", "execution", "settlement_claim")
REQUIREMENTS = (
    "payer_identity",
    "source_documents",
    "recipient_destination",
    "current_obligation",
    "exact_payment_terms",
    "human_approvals",
    "independent_payment_verification",
    "duplicate_resolution",
    "policy_clarification",
)


BLOCKER_SEMANTICS_VERSION = "finance-stage-vocabulary-v1"
BLOCKER_SEMANTICS = """Protected output vocabulary (interpretation only; never financial authority):
- A blocker names an actually missing prerequisite at the earliest operation it prevents, not a generic checklist. Do not move a prerequisite to execution if it already prevents approval-request preparation. Do not block a supported reported obligation merely because later payment prerequisites are missing.
- obligation_recording: establish the remaining liability, creditor/payer, amount and currency from current evidence. approval_request: prepare an exact current payment proposal. execution: obtain the service-required human approvals for that exact action. settlement_claim: assert independently confirmed payment completion.
- payer_identity: who actually paid and whom the event owes. source_documents: missing or contradictory transaction evidence needed for the stated operation. recipient_destination: verified payment routing, first required for approval_request. current_obligation: a current unsettled obligation/version needed for the payment proposal.
- exact_payment_terms: missing or conflicting transaction amount, currency, asset or network. policy_clarification: missing/conflicting governing rule or who has authority to decide; it is not a synonym for every missing transaction fact.
- human_approvals: execution authorization, not permission to record or request approval. independent_payment_verification: evidence needed to claim settlement; do not turn a reported obligation into a settled payment. duplicate_resolution: determine whether the same underlying liability or an earlier unresolved transfer would be paid again; resolve before preparing another payment request.
- A supporting reference must identify an observed source/version or an actually supplied protected policy/rule. Never invent a policy ID. Unknown policy remains a question for the authorized human; output labels do not confer permission.
"""


def validate_decision_shape(output: dict) -> None:
    if not isinstance(output.get("decision"), str) or not re.fullmatch(
        DECISION_CLASSIFICATION_PATTERN, output["decision"]
    ):
        raise ValueError("decision")
    if not isinstance(output.get("explanation"), str) or not output["explanation"].strip():
        raise ValueError("explanation")
    sources = output.get("evidence_source_ids")
    if not isinstance(sources, list) or any(not isinstance(source, str) for source in sources):
        raise ValueError("sources")
    if (
        "clarification" not in output
        or output["clarification"] is not None
        and not isinstance(output["clarification"], str)
    ):
        raise ValueError("clarification")
    if (
        "proposed_action" not in output
        or output["proposed_action"] is not None
        and not isinstance(output["proposed_action"], dict)
    ):
        raise ValueError("proposed_action")
    action = output["proposed_action"]
    if isinstance(action, dict) and action.get("action") not in PREPARED_ACTIONS:
        raise ValueError("proposed_action_kind")
    if isinstance(action, dict) and "evidence_refs" in action:
        refs = action["evidence_refs"]
        if not isinstance(refs, list) or any(
            not isinstance(ref, dict) or not isinstance(ref.get("id"), str)
            or type(ref.get("version")) is not int or ref["version"] < 1
            for ref in refs
        ):
            raise ValueError("action_evidence_refs")
    blockers = output.get("blocking_requirements")
    if not isinstance(blockers, list) or len(blockers) > 100:
        raise ValueError("blocking_requirements")
    for blocker in blockers:
        if (
            not isinstance(blocker, dict)
            or blocker.get("stage") not in STAGES
            or blocker.get("requirement") not in REQUIREMENTS
        ):
            raise ValueError("blocker")
        refs = blocker.get("supporting_refs")
        if not isinstance(refs, list) or not refs or len(refs) > 20:
            raise ValueError("blocker_refs")
        for ref in refs:
            if (
                not isinstance(ref, dict)
                or ref.get("kind") not in {"policy", "source"}
                or not isinstance(ref.get("id"), str)
                or type(ref.get("version")) is not int
                or ref["version"] < 1
            ):
                raise ValueError("blocker_ref")

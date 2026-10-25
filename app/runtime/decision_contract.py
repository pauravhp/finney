"""Neutral decision representation; it does not define financial permissions."""

import re

OUTPUT_CONTRACT = "finance-decision-v2"
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

"""Contract semantics shared by every protected evaluator.

Canonicalization never consults the expected answer, case name, supplier or
explanation. Raw provider output remains unchanged in its original trace.
"""

EVALUATOR_VERSION = "finance-evaluator-v2"


def normalize_prepared_output(output: dict) -> dict:
    if "proposed_action" not in output:
        raise ValueError("proposed_action_missing")
    normalized = dict(output)
    question = output.get("clarification")
    if question is not None and not isinstance(question, str):
        raise ValueError("clarification_invalid")
    if isinstance(question, str) and not question.strip():
        question = None
        normalized["clarification"] = None
    if output["proposed_action"] is None:
        if question is None:
            normalized["proposed_action"] = {"action": "no_action"}
        elif isinstance(question, str):
            normalized["proposed_action"] = {"action": "investigate"}
        else:
            raise ValueError("clarification_invalid")
    return normalized

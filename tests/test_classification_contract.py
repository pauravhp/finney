"""Producer/runtime/persistence classification agreement; no provider or DB writes."""
import copy

import pytest

from app.finance.review_persistence import _prepared_output
from app.finance.types import FinanceError
from app.runtime.decision_contract import (
    DECISION_CLASSIFICATION_SCHEMA,
    OUTPUT_CONTRACT,
    validate_decision_shape,
)
from app.runtime.hermes import _actor_output
from app.runtime.opencode import _system, output_schema

OUTPUT = {"decision": "investigate", "explanation": "A source-linked clarification is required.",
          "evidence_source_ids": ["source-fixture"], "clarification": "Who paid?",
          "proposed_action": None, "blocking_requirements": []}


@pytest.mark.parametrize("classification", ["a", "investigate", "no_action2", "a__", "a" + "_" * 79])
def test_existing_persisted_classifications_pass_unchanged(classification):
    output = {**OUTPUT, "decision": classification}
    original = copy.deepcopy(output)
    validate_decision_shape(output)
    assert _prepared_output(output)["decision"] == classification
    assert output == original


@pytest.mark.parametrize("classification", [
    "", " ", "Pause; await a verifiable invoice.", "Investigate", "no-action", "_investigate",
    "1investigate", "a" * 81, "investigate\n", "investigate ", "évidence", True, 123, None, {}, [],
])
def test_invalid_classification_is_rejected_without_reinterpretation(classification):
    output = {**OUTPUT, "decision": classification}
    original = copy.deepcopy(output)
    with pytest.raises(ValueError, match="^decision$"):
        validate_decision_shape(output)
    with pytest.raises(FinanceError, match="invalid review classification"):
        _prepared_output(output)
    assert output == original


def test_native_finance_schema_and_guidance_state_existing_persisted_requirement():
    assert output_schema("finance")["properties"]["decision"] == DECISION_CLASSIFICATION_SCHEMA
    assert DECISION_CLASSIFICATION_SCHEMA == {
        "type": "string", "minLength": 1, "maxLength": 80,
        "pattern": "^[a-z][a-z0-9_]{0,79}$",
    }
    assert DECISION_CLASSIFICATION_SCHEMA["pattern"] in _system("unchanged skill", "finance", False, None)
    assert "decision must be" not in _system("unchanged skill", "finance", True, None)
    assert "decision" not in output_schema("editor")["properties"]
    assert "decision" not in output_schema("onboarding")["properties"]
    assert OUTPUT_CONTRACT == "finance-decision-v2"


def test_hermes_format_recovery_never_converts_prose_into_a_classification():
    import json

    from app.models import ModelError

    raw = "Observed result: " + json.dumps({**OUTPUT, "decision": "Pause pending invoice verification."})
    with pytest.raises(ModelError, match="invalid_finance_decision_schema"):
        _actor_output(raw, finance=True)

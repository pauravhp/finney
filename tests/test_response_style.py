"""Prompt/schema boundaries; no claimed model behavior or inferred quality gain."""
import pytest

from app.runtime.decision_contract import USER_FACING_RESPONSE_STYLE
from app.runtime.opencode import _system, output_schema


@pytest.mark.parametrize("mode,conversation", [("finance", True), ("finance", False), ("onboarding", False)])
def test_native_user_facing_prompts_get_style_without_losing_authority_or_schema(mode, conversation):
    prompt = _system("Fixture task guidance", mode, conversation, {"id": "fixture-policy"})
    assert USER_FACING_RESPONSE_STYLE in prompt
    assert "Fixture task guidance" in prompt
    if mode == "finance":
        assert "Never approve" in prompt and "Keep uncertainty visible" in prompt
        assert "fixture-policy" in prompt
        if not conversation:
            assert "StructuredOutput" in prompt and "supporting_refs" in prompt
    else:
        assert "structured setup object" in prompt and "Never request" in prompt


def test_editor_and_machine_evidence_schema_are_not_shortened():
    assert USER_FACING_RESPONSE_STYLE not in _system("Procedure editor", "editor", False, None)
    schema = output_schema("finance")
    assert set(schema["required"]) == {"decision", "explanation", "evidence_source_ids", "clarification",
                                       "proposed_action", "blocking_requirements"}
    # Concision remains prompt guidance, not a hard output-length gate.
    assert "maxLength" not in schema["properties"]["explanation"]
    assert schema["properties"]["blocking_requirements"]["items"]["properties"]["supporting_refs"]["minItems"] == 1

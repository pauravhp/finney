"""Bounded failure observations for diagnosis, never a valid finance decision.

Only the trusted worker writes these projections. Raw output, tool arguments,
source text and provider metadata remain in a private artifact, excluded from
reviewer context. Nothing here retries inference or changes a finance validator.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .decision_contract import validate_decision_shape

FAILURE_OBSERVATION_CONTRACT = "finance-failure-observation-v1"
MAX_DIAGNOSTIC_BYTES = 512_000
MAX_OBSERVED_TOOLS = 64
ELIGIBLE_FAILURES = frozenset({
    "invalid_finance_decision_schema", "model_output_not_json_object",
    "model_output_ambiguous_json", "model_output_multiple_json_objects",
    "model_output_incomplete_for_format_recovery",
    "model_output_not_recoverable_without_new_content", "hermes_timeout",
    "hermes_incomplete_outcome", "hermes_truncated_output",
    "hermes_provider_or_runtime_failure", "hermes_process_exited_without_result",
    "hermes_protocol_error", "hermes_invalid_api_call_count",
    "opencode_structured_output_missing", "opencode_truncated_output",
    "opencode_incomplete_outcome", "opencode_tool_not_permitted",
    "opencode_provider_or_runtime_failure", "evaluation_model_call_budget_exhausted",
})
SCHEMA_ERRORS = frozenset({
    "decision", "explanation", "sources", "clarification", "proposed_action",
    "blocking_requirements", "blocker", "blocker_refs", "blocker_ref",
})


def private_failure_artifact(diagnostic: dict) -> str:
    """Preserve bounded private diagnostic bytes with explicit truncation receipt."""
    encoded = json.dumps(diagnostic, sort_keys=True, ensure_ascii=True).encode()
    if len(encoded) <= MAX_DIAGNOSTIC_BYTES:
        return encoded.decode()
    return json.dumps({
        "truncated": True, "original_bytes": len(encoded),
        "original_sha256": hashlib.sha256(encoded).hexdigest(),
        "diagnostic_json_prefix": encoded[:MAX_DIAGNOSTIC_BYTES // 4].decode(),
    }, ensure_ascii=True)


def failure_observations(reason: str, diagnostic: dict) -> dict:
    """No model prose or free-form exception text crosses this projection."""
    events = diagnostic.get("tool_events")
    events = events if isinstance(events, list) else []
    observations: dict[str, Any] = {
        "contract": FAILURE_OBSERVATION_CONTRACT,
        "reason": reason if reason in ELIGIBLE_FAILURES else "actor_runtime_failure",
        "actor_status": "failed", "financial_output_valid": False,
        "tool_event_count": len(events), "tool_events_truncated": len(events) > MAX_OBSERVED_TOOLS,
    }
    calls = diagnostic.get("api_calls")
    limit = diagnostic.get("granted_max_model_calls")
    if type(calls) is int and 0 <= calls <= 40:
        observations["api_calls"] = calls
    if type(limit) is int and 1 <= limit <= 40:
        observations["granted_max_model_calls"] = limit
    # Re-run the unchanged validator only to name its fixed schema field.
    raw = diagnostic.get("original_final_response")
    if reason == "invalid_finance_decision_schema" and isinstance(raw, str) and len(raw) <= 131_072:
        try:
            output = json.loads(raw)
            if isinstance(output, dict):
                validate_decision_shape(output)
        except ValueError as error:
            if str(error) in SCHEMA_ERRORS:
                observations["schema_error"] = str(error)
        except (TypeError, AttributeError):
            pass
    return observations


def eligible_failed_trace(payload: dict) -> bool:
    observations = payload.get("failure_observations", {})
    return (
        payload.get("actor_status") == "failed"
        and payload.get("improvement_eligible") is True
        and payload.get("mutable_skill_name") == "organizer-expenses"
        and payload.get("command_type") == "review_case"
        and payload.get("inference_reservation", {}).get("claimed") is True
        and bool(payload.get("skill_version"))
        and bool(payload.get("runtime_context_artifact", {}).get("artifact_path"))
        and bool(payload.get("diagnostic_artifact", {}).get("artifact_path"))
        and observations.get("contract") == FAILURE_OBSERVATION_CONTRACT
        and observations.get("financial_output_valid") is False
        and observations.get("reason") in ELIGIBLE_FAILURES
        and (observations.get("reason") != "evaluation_model_call_budget_exhausted"
             or type(observations.get("api_calls")) is int and observations["api_calls"] > 0)
        and "output" not in payload
    )


def failed_improvement_request(job: dict, outcome: dict, *, suite_id: str) -> dict | None:
    if (
        job.get("command_type") != "review_case" or outcome.get("status") != "blocked"
        or outcome.get("improvement_eligible") is not True or not suite_id
        or not outcome.get("failure_trace", {}).get("id")
        or outcome.get("failure_observations", {}).get("contract") != FAILURE_OBSERVATION_CONTRACT
    ):
        return None
    trace_id = outcome["failure_trace"]["id"]
    return {
        "payload": {"trace_id": trace_id, "suite_id": suite_id, "trigger": "failed_case_review"},
        "idempotency_key": f"improvement-review:{trace_id}",
    }

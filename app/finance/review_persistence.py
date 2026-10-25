"""Persist an observed model review as an annotation, never financial authority."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from app.finance.types import FinanceError, minor_units


def _blocked(reason: str) -> dict[str, str]:
    return {"status": "blocked", "reason": reason}


def _prepared_output(output: Any) -> dict[str, Any]:
    if not isinstance(output, dict) or not re.fullmatch(
        r"[a-z][a-z0-9_]{0,79}", str(output.get("decision", ""))
    ):
        raise FinanceError("invalid review classification")
    sources, clarification, explanation = (
        output.get("evidence_source_ids"),
        output.get("clarification"),
        output.get("explanation"),
    )
    if (
        not isinstance(sources, list)
        or len(sources) > 200
        or any(not isinstance(value, str) or not value for value in sources)
    ):
        raise FinanceError("invalid review citations")
    if clarification is not None and (
        not isinstance(clarification, str) or not clarification.strip() or len(clarification) > 4000
    ):
        raise FinanceError("invalid review clarification")
    if not isinstance(explanation, str) or not explanation.strip() or len(explanation) > 12000:
        raise FinanceError("invalid review explanation")
    action = copy.deepcopy(output.get("proposed_action"))
    if action is not None:
        if not isinstance(action, dict) or action.get("action") not in {
            "pay_vendor",
            "reimburse_organizer",
            "investigate",
            "no_action",
        }:
            raise FinanceError("invalid prepared action")
        if any(
            key in action
            for key in (
                "executed",
                "paid",
                "settled",
                "approved",
                "approval_count",
                "provider_reference",
            )
        ):
            raise FinanceError("a prepared action cannot assert external authority or settlement")
        if "amount_minor" in action:
            action["amount_minor"] = str(minor_units(action["amount_minor"], nonnegative=True))
        refs = action.get("evidence_refs", [])
        if not isinstance(refs, list) or any(
            not isinstance(ref, dict)
            or not isinstance(ref.get("id"), str)
            or isinstance(ref.get("version"), bool)
            or not isinstance(ref.get("version"), int)
            or ref["version"] < 1
            for ref in refs
        ):
            raise FinanceError("invalid prepared source references")
    blockers = output.get("blocking_requirements", [])
    if not isinstance(blockers, list):
        raise FinanceError("invalid blocking requirements")
    result = {
        "decision": output["decision"],
        "evidence_source_ids": sources,
        "clarification": clarification,
        "proposed_action": action,
        "explanation": explanation,
        "blocking_requirements": copy.deepcopy(blockers),
    }
    if len(json.dumps(result, allow_nan=False).encode()) > 32000:
        raise FinanceError("review annotation too large")
    return result


async def persist_actor_review(
    tools: Any, before_case: dict[str, Any] | None, outcome: dict[str, Any], job: dict[str, Any]
) -> dict[str, Any]:
    if job.get("command_type") not in {"review_case", "director_message"} or outcome.get("status") != "completed":
        return {"status": "skipped", "reason": "no_completed_case_review"}
    if getattr(tools, "prepare_only", False):
        return _blocked("evaluation_cannot_persist_operating_review")
    if not isinstance(before_case, dict) or str(before_case.get("id")) != str(
        job.get("payload", {}).get("case_id")
    ):
        return _blocked("review_case_context_mismatch")
    case_id = str(before_case["id"])
    expected = before_case.get("version")
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
        return _blocked("review_case_version_required")
    initial_version = expected
    source_ids = copy.deepcopy(before_case.get("data", {}).get("source_ids", []))
    trace_id = outcome.get("trace", {}).get("id")
    if not trace_id:
        return _blocked("completed_actor_trace_required")
    trace = await tools.call("get_trace", {"trace_id": trace_id})
    payload = trace.get("payload", {}) if isinstance(trace, dict) else {}
    if (
        not trace
        or trace.get("event_type") != "actor_completed"
        or str(payload.get("job_id")) != str(job.get("id"))
        or payload.get("output") != outcome.get("output")
        or payload.get("tool_events", []) != outcome.get("tool_events", [])
    ):
        return _blocked("completed_actor_trace_mismatch")
    if not payload.get("skill_version"):
        return _blocked("review_skill_provenance_required")
    try:
        prepared = _prepared_output(outcome.get("output"))
    except (FinanceError, TypeError, ValueError):
        return _blocked("unsupported_prepared_review_output")
    for event in outcome.get("tool_events", []):
        args, result = event.get("arguments", {}), event.get("result", {})
        if (
            event.get("name") != "record_finding"
            or str(args.get("case_id")) != case_id
            or not isinstance(result, dict)
            or result.get("status") in {"failed", "blocked"}
            or result.get("error")
        ):
            continue
        if (
            args.get("expected_version") != expected
            or str(result.get("case_id")) != case_id
            or result.get("version") != expected + 1
        ):
            return _blocked("review_case_version_chain_invalid")
        expected += 1
    references = (
        prepared.get("proposed_action", {}).get("evidence_refs", [])
        if prepared.get("proposed_action")
        else []
    )
    citations = set(prepared["evidence_source_ids"]) | {ref["id"] for ref in references}
    if not citations.issubset(set(source_ids)) or references:
        snapshot = await tools.call("get_finance_snapshot", {})
        scoped = {
            str(source["id"]): source.get("version") for source in snapshot.get("source_items", [])
        }
        if not citations.issubset(set(scoped)) or any(
            scoped[ref["id"]] != ref["version"] for ref in references
        ):
            return _blocked("review_citation_outside_scope_or_version")
    current = await tools.call("get_case", {"case_id": case_id})
    marker = current.get("data", {}).get("finding", {})
    if (
        isinstance(marker, dict)
        and marker.get("kind") == "prepared_agent_review"
        and marker.get("provenance", {}).get("actor_trace_id") == trace_id
        and marker.get("provenance", {}).get("job_id") == str(job["id"])
    ):
        return {"status": "already_persisted", "case_id": case_id, "version": current["version"]}
    if (
        current.get("version") != expected
        or current.get("data", {}).get("source_ids", []) != source_ids
    ):
        return _blocked("review_context_changed_requires_new_review")
    finding = {
        "kind": "prepared_agent_review",
        "verification": "unverified_model_recommendation",
        "effects_completed": False,
        **prepared,
        "provenance": {
            "job_id": str(job["id"]),
            "actor_trace_id": trace_id,
            "skill_version_id": payload["skill_version"],
            "source_case_version": initial_version,
            "source_ids": source_ids,
            "output_sha256": hashlib.sha256(
                json.dumps(
                    outcome["output"], sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()
            ).hexdigest(),
        },
    }
    try:
        return await tools.call(
            "record_case_review",
            {
                "case_id": case_id,
                "expected_version": expected,
                "expected_source_ids": source_ids,
                "trace_id": trace_id,
                "job_id": str(job["id"]),
                "finding": finding,
                "idempotency_key": "case-review:" + str(job["id"]),
            },
        )
    except (FinanceError, RuntimeError):
        # The DB checks the same context atomically; no blind retry with fresh state.
        return _blocked("review_context_or_persistence_changed")

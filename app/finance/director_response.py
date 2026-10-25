"""Append actual conversational replies without manufacturing finance decisions."""

from __future__ import annotations

import copy
from typing import Any
from uuid import UUID

from .types import FinanceError

DIRECTOR_OUTPUT_CONTRACT = "finance-director-response-v1"


def _successful(result: Any) -> bool:
    return (
        isinstance(result, dict)
        and result.get("error") in (None, False, "", 0)
        and result.get("success") is not False
        and result.get("status") not in ("failed", "blocked", "error")
    )


def _identity(value: Any) -> str:
    try:
        valid = isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise FinanceError("canonical source identity required")
    return value


def _refs(values: Any) -> list[dict]:
    if not isinstance(values, list) or len(values) > 200:
        raise FinanceError("bounded consulted source references required")
    found = {}
    for item in values:
        if not isinstance(item, dict) or set(item) != {"id", "version"}:
            raise FinanceError("versioned consulted source required")
        identity = _identity(item["id"])
        version = item["version"]
        if type(version) is not int or not 1 <= version <= 2147483647:
            raise FinanceError("integer consulted source version required")
        if identity in found and found[identity] != version:
            raise FinanceError("conflicting consulted source versions")
        found[identity] = version
    return [{"id": identity, "version": found[identity]} for identity in sorted(found)]


def consulted_source_refs(events: Any) -> list[dict]:
    """Trusted metadata from successful document/thread results, never prose cites."""
    if not isinstance(events, list):
        raise FinanceError("actual tool event list required")
    values = []
    for event in events:
        if not isinstance(event, dict) or event.get("name") not in {"read_document", "read_thread"}:
            continue
        result = event.get("result")
        if not _successful(result):
            continue
        documents = [result] if event["name"] == "read_document" else result.get("documents")
        if not isinstance(documents, list):
            raise FinanceError("actual thread document list required")
        for document in documents:
            if _successful(document):
                values.append({"id": document.get("id"), "version": document.get("version")})
    return _refs(values)


def _source_ids(values: Any) -> list[str]:
    if not isinstance(values, list) or len(values) > 200:
        raise FinanceError("bounded source identity list required")
    ids = [_identity(value) for value in values]
    if len(ids) != len(set(ids)):
        raise FinanceError("distinct source identities required")
    return ids


async def persist_director_response(
    tools: Any, before_case: dict | None, outcome: dict, job: dict
) -> dict:
    """The protected RPC rechecks all provenance, authority and CAS atomically."""
    if job.get("command_type") != "director_message" or outcome.get("status") != "completed":
        return {"status": "skipped", "reason": "no_completed_director_response"}
    if getattr(tools, "prepare_only", False):
        return {"status": "blocked", "reason": "evaluation_cannot_persist_director_response"}
    if not isinstance(before_case, dict) or str(before_case.get("id")) != str(
        job.get("payload", {}).get("case_id")
    ):
        return {"status": "blocked", "reason": "director_response_case_context_mismatch"}
    expected = before_case.get("version")
    if type(expected) is not int or expected < 1:
        return {"status": "blocked", "reason": "director_response_case_version_required"}
    trace_id = outcome.get("trace", {}).get("id")
    if not trace_id:
        return {"status": "blocked", "reason": "completed_director_trace_required"}
    captured = await tools.call("get_trace", {"trace_id": trace_id})
    payload = captured.get("payload", {}) if isinstance(captured, dict) else {}
    if (
        not captured
        or captured.get("event_type") != "actor_completed"
        or str(payload.get("job_id")) != str(job.get("id"))
        or payload.get("output") != outcome.get("output")
        or payload.get("tool_events", []) != outcome.get("tool_events", [])
        or payload.get("evidence", {}).get("output_contract") != DIRECTOR_OUTPUT_CONTRACT
        or outcome.get("evidence", {}).get("output_contract") != DIRECTOR_OUTPUT_CONTRACT
        or payload.get("improvement_eligible") is not False
        or not payload.get("skill_version")
    ):
        return {"status": "blocked", "reason": "completed_director_trace_mismatch"}
    try:
        output = outcome.get("output")
        if not isinstance(output, dict) or set(output) != {
            "response_type",
            "message",
            "evidence_source_ids",
            "consulted_source_refs",
        }:
            raise FinanceError("director response shape required")
        message = output["message"]
        if (
            output["response_type"] != "director_response"
            or not isinstance(message, str)
            or not message.strip()
            or len(message) > 16000
        ):
            raise FinanceError("bounded actual director message required")
        source_ids = _source_ids(before_case.get("data", {}).get("source_ids", []))
        refs = consulted_source_refs(payload.get("tool_events", []))
        declared = _refs(output["consulted_source_refs"])
        if len(declared) != len(output["consulted_source_refs"]) or declared != refs:
            raise FinanceError("consulted references must match successful reads")
        if sorted(_source_ids(output["evidence_source_ids"])) != [ref["id"] for ref in refs]:
            raise FinanceError("consulted identities must match successful reads")
    except (FinanceError, TypeError, ValueError, KeyError):
        return {"status": "blocked", "reason": "unsupported_director_response_provenance"}
    if source_ids or refs:
        snapshot = await tools.call("get_finance_snapshot", {})
        scoped = {
            str(source["id"]): source.get("version") for source in snapshot.get("source_items", [])
        }
        if not set(source_ids).issubset(scoped) or any(
            scoped.get(ref["id"]) != ref["version"] for ref in refs
        ):
            return {
                "status": "blocked",
                "reason": "director_consulted_source_outside_scope_or_version",
            }
    current = await tools.call("get_case", {"case_id": before_case["id"]})
    existing = current.get("data", {}).get("director_responses", [])
    same = (
        [
            item
            for item in existing
            if isinstance(item, dict) and item.get("job_id") == str(job["id"])
        ]
        if isinstance(existing, list)
        else []
    )
    if not same and (
        current.get("version") != expected
        or current.get("data", {}).get("source_ids", []) != source_ids
    ):
        return {
            "status": "blocked",
            "reason": "director_response_context_changed_requires_new_request",
        }
    response = {
        "message": message,
        "consulted_source_ids": [ref["id"] for ref in refs],
        "consulted_source_refs": refs,
        "provenance": {
            "source_case_version": expected,
            "source_ids": copy.deepcopy(source_ids),
        },
    }
    try:
        return await tools.call(
            "record_director_response",
            {
                "case_id": str(before_case["id"]),
                "expected_version": expected,
                "expected_source_ids": source_ids,
                "trace_id": str(trace_id),
                "job_id": str(job["id"]),
                "response": response,
                "idempotency_key": "director-response:" + str(job["id"]),
            },
        )
    except (FinanceError, RuntimeError):
        return {
            "status": "blocked",
            "reason": "director_response_authority_context_or_persistence_changed",
        }

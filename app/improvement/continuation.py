"""Trusted, one-shot continuation of an archived search before any evaluation.

No new search, attempt claim, reservation reset, or changed evaluation is allowed.
This coordinator API is not an actor tool or a public command. Read-only SQL
proves the interrupted boundary; all writes use existing guarded finance tools.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from app.improvement.decisions import EVALUATOR_VERSION
from app.improvement.engine import (
    EDIT_END,
    EDIT_START,
    GATE_VERSION,
    HARNESS2_MAX_MODEL_CALLS,
    SKILL_NAME,
    ImprovementEngine,
    _AttemptState,
    diagnosis_has_trace_support,
    evaluation_manifest,
    replace_procedure,
)
from app.improvement.harness2_candidate import PROBE_CALL_LIMIT, captured_training_snapshot
from app.improvement.harness2_search import HARNESS2_REVISION, verify_harness2
from app.improvement.promotion_suite import (
    PROMOTION_MANIFEST_SHA256,
    PROMOTION_SUITE_ID,
    PromotionEvaluationTools,
    promotion_suite,
)
from app.models import ModelError
from app.runtime.decision_contract import OUTPUT_CONTRACT
from app.runtime.opencode import OpenCodeActor
from app.runtime.opencode_setup import verify_binary
from app.runtime.trace_contract import trace_contract_signals

# This narrow recovery contract is bound to the complete original answer-key
# manifest, not only the native suite's minimal action hashes. A future dataset
# requires a separately reviewed recovery contract rather than changing this pin.
CONTINUATION_DATASET_SHA256 = "d7e9b6863877a21d79c302d24659f788721fbeef98593bcaf11d25a9aa23d8ab"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _fail(code: str):
    raise ModelError("continuation_" + code)


def _row(connection, query: str, params: tuple) -> dict | None:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, params)
        return cursor.fetchone()


async def _artifact(tools, receipt: dict) -> tuple[str, dict]:
    if (not isinstance(receipt, dict) or not isinstance(receipt.get("artifact_path"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", receipt.get("content_sha256", ""))):
        _fail("artifact_receipt_invalid")
    raw = await tools.call("read_artifact", {"artifact_path": receipt["artifact_path"]})
    content = raw.get("content")
    if not isinstance(content, str) or len(content.encode()) > 10_485_760 or _sha(content) != receipt["content_sha256"]:
        _fail("artifact_hash_mismatch")
    try:
        value = json.loads(content)
    except ValueError:
        _fail("artifact_json_invalid")
    if not isinstance(value, dict):
        _fail("artifact_object_required")
    return content, value


async def _archived_selection(tools, receipt: dict) -> tuple[dict, dict]:
    _raw, manifest = await _artifact(tools, receipt)
    if (manifest.get("contract") != "finney-harness2-artifact-manifest-v1"
            or manifest.get("status") != "selected" or manifest.get("harness2_revision") != HARNESS2_REVISION
            or not isinstance(manifest.get("parts"), list) or not 1 <= len(manifest["parts"]) <= 16):
        _fail("search_manifest_invalid")
    chunks, size = [], 0
    for part in manifest["parts"]:
        raw, payload = await _artifact(tools, part)
        size += len(raw.encode())
        if size > 64_000_000 or payload.get("contract") != "finney-harness2-artifact-part-v1" or not isinstance(payload.get("records"), list):
            _fail("search_parts_invalid")
        chunks.extend(row for row in payload["records"] if isinstance(row, dict) and row.get("path") == "__search_result__.json")
    if not chunks or any(type(row.get("chunk_index")) is not int or type(row.get("chunk_count")) is not int for row in chunks):
        _fail("search_result_chunks_invalid")
    chunks.sort(key=lambda row: row["chunk_index"])
    if ([row["chunk_index"] for row in chunks] != list(range(len(chunks)))
            or any(row["chunk_count"] != len(chunks) or row.get("file_sha256") != chunks[0].get("file_sha256")
                   or not isinstance(row.get("text"), str) for row in chunks)):
        _fail("search_result_chunks_invalid")
    content = "".join(row["text"] for row in chunks)
    if _sha(content) != chunks[0].get("file_sha256"):
        _fail("search_result_hash_mismatch")
    try:
        result = json.loads(content)
    except ValueError:
        _fail("search_result_json_invalid")
    if not isinstance(result, dict):
        _fail("search_result_invalid")
    return manifest, result


async def continue_archived_search(*, connection, tools, actor: OpenCodeActor,
                                   attempt_id: str, archive_receipt: dict,
                                   validate_only: bool = False) -> dict:
    """Continue one unfinished promotion-v1 attempt, under its original budget.

    `connection` is a trusted read-only-capable psycopg connection. `tools` is the
    original scope-bound IntegratedTools coordinator facade, with native shared
    holdout claims. The function reads the selected candidate from verified
    private artifacts; callers cannot supply a patch, scores or expected answers.
    A failed durable continuation claim is never retried here.
    """
    started = time.perf_counter()
    if PROMOTION_MANIFEST_SHA256 != CONTINUATION_DATASET_SHA256:
        _fail("original_full_dataset_manifest_changed")
    attempt_id = str(UUID(attempt_id))
    organization, run = str(tools.scope.organization_id), str(tools.scope.run_id)
    scope = (organization, run)
    if not isinstance(actor, OpenCodeActor):
        _fail("opencode_required")
    verify_harness2()
    verify_binary(actor.binary)
    attempt = _row(connection, "select * from finance_improvement_attempts where organization_id=%s and run_id=%s and id=%s", (*scope, attempt_id))
    if (not attempt or attempt["status"] != "claimed" or attempt["eval_run_id"] is not None
            or attempt["model_calls_used"] is not None or attempt["finished_at"] is not None
            or attempt["max_model_calls"] != HARNESS2_MAX_MODEL_CALLS
            or attempt["suite_id"] != PROMOTION_SUITE_ID or attempt["evaluator_version"] != EVALUATOR_VERSION):
        _fail("unfinished_original_attempt_required")
    job = _row(connection, "select * from jobs where organization_id=%s and run_id=%s and id=%s", (*scope, attempt_id))
    if (not job or job["status"] != "failed" or job["command_type"] != "evaluate_improvement"
            or job.get("error_code") != "runtime_dependency_or_persistence_failure"
            or job["payload"].get("trace_id") != str(attempt["trace_id"])
            or job["payload"].get("suite_id") != PROMOTION_SUITE_ID):
        _fail("original_failed_search_job_required")
    for query, parameters in (
        ("select 1 from eval_runs where organization_id=%s and run_id=%s and metrics->>'attempt_id'=%s limit 1", (*scope, attempt_id)),
        ("select 1 from eval_results where organization_id=%s and run_id=%s and details->>'attempt_id'=%s limit 1", (*scope, attempt_id)),
        ("select 1 from skill_versions where organization_id=%s and run_id=%s and version=%s limit 1", (*scope, attempt_id)),
        ("select 1 from finance_improvement_holdouts where organization_id=%s and run_id=%s and attempt_id=%s limit 1", (*scope, attempt_id)),
        ("select 1 from finance_learning_holdouts where organization_id=%s and run_id=%s and dataset_sha256=%s limit 1", (*scope, PROMOTION_MANIFEST_SHA256)),
        ("select 1 from trace_events where organization_id=%s and run_id=%s and idempotency_key=%s limit 1", (*scope, f"improvement:{attempt_id}:continue-post-search")),
    ):
        if _row(connection, query, parameters):
            _fail("evaluation_or_continuation_already_started")
    traces = {}
    for phase in ("observed", "flagged", "diagnosed"):
        row = _row(connection, "select payload from trace_events where organization_id=%s and run_id=%s and idempotency_key=%s", (*scope, f"improvement:{attempt_id}:{phase}"))
        if not row or row["payload"].get("attempt_id") != attempt_id:
            _fail("original_phase_receipt_required")
        traces[phase] = row["payload"]
    diagnosis = traces["diagnosed"].get("output", {})
    if diagnosis.get("issue_type") != "procedure_defect" or not diagnosis.get("evidence_pointers") or not diagnosis.get("trace_references"):
        _fail("original_qualified_diagnosis_required")
    baseline = await tools.call("get_active_skill", {"skill_name": SKILL_NAME})
    if not baseline or baseline.get("id") != str(attempt["baseline_version_id"]):
        _fail("original_baseline_not_active")
    baseline_raw = await tools.call("read_artifact", {"artifact_path": baseline["artifact_path"]})
    baseline_content = baseline_raw.get("content")
    if not isinstance(baseline_content, str) or _sha(baseline_content) != baseline.get("content_sha256"):
        _fail("baseline_hash_mismatch")
    source = _row(connection, "select id,event_type,payload from trace_events where organization_id=%s and run_id=%s and id=%s", (*scope, attempt["trace_id"]))
    if not source or source["event_type"] != "actor_completed" or source["payload"].get("skill_version") != baseline["id"]:
        _fail("original_actor_trace_required")
    trace = {**source["payload"], "id": str(source["id"])}
    _raw, context = await _artifact(tools, trace.get("runtime_context_artifact"))
    fixed, policy = context.get("fixed_context"), context.get("immutable_policy")
    if (not isinstance(fixed, dict) or set(fixed) != {"prefix", "suffix", "active_skill_sha256"}
            or not all(isinstance(value, str) for value in fixed.values())
            or fixed["active_skill_sha256"] != baseline["content_sha256"]
            or _sha(fixed["prefix"] + baseline_content + fixed["suffix"]) != trace.get("context_sha256")):
        _fail("runtime_context_mismatch")
    from app.runtime.jobs import improvement_review_request
    trace["review_request"] = improvement_review_request(job)
    observed_sources = {}
    for event in trace.get("tool_events", []):
        value = event.get("result") if isinstance(event, dict) else None
        if (isinstance(event, dict) and event.get("name") == "read_document" and isinstance(value, dict)
                and isinstance(value.get("id"), str) and type(value.get("version")) is int):
            observed_sources[value["id"]] = {"id": value["id"], "version": value["version"]}
    trace["contract_signals"] = trace_contract_signals(
        trace.get("output"), protected_policy=policy,
        current_source_refs=list(observed_sources.values()) or None,
        captured_tool_events=trace.get("tool_events"),
    )
    trace["policy_provenance"] = {"status": "captured_runtime_context", "evaluation_policy_is_not_observed_policy": True}
    if not diagnosis_has_trace_support(diagnosis, {"trace": trace, "immutable_policy": policy}):
        _fail("original_diagnosis_pointers_invalid")
    inputs = traces["observed"].get("frozen_inputs_artifact")
    frozen_content, _frozen = await _artifact(tools, inputs)
    wrapped = PromotionEvaluationTools(tools, tools.claim_corpus_holdout)
    suite = promotion_suite(wrapped).frozen_copy()
    suite.validate()
    current_manifest = evaluation_manifest(actor, suite, fixed_context=fixed, observed_policy=policy, method="harness2")
    if (frozen_content != current_manifest or _sha(frozen_content) != attempt["suite_manifest_sha256"]
            or attempt["case_manifest"] != [{"case_key": case.case_key, "group": case.group, "source_snapshot_hash": case.source_snapshot_hash} for case in suite.cases]):
        _fail("frozen_model_suite_or_context_changed")
    manifest, archive = await _archived_selection(tools, archive_receipt)
    # The archive must have existed during the failed original job, not be a
    # replacement candidate manufactured for this continuation.
    stored = _row(connection, "select to_jsonb(o)->>'created_at' created_at from storage.objects o where bucket_id='finance-artifacts' and name=%s", (archive_receipt["artifact_path"],))
    if not stored or not stored["created_at"]:
        _fail("original_archive_timestamp_required")
    created = datetime.fromisoformat(stored["created_at"])
    if not attempt["created_at"] <= created <= job["updated_at"]:
        _fail("archive_outside_original_attempt")
    _raw, training = await _artifact(tools, manifest.get("training_context_artifact"))
    snapshot, provenance = await captured_training_snapshot(trace, tools)
    if (training.get("contract") != "finney-harness2-training-v1"
            or training.get("baseline_sha256") != baseline["content_sha256"]
            or training.get("immutable_runtime_context") != fixed or training.get("immutable_policy") != policy
            or training.get("snapshot") != snapshot or training.get("provenance") != provenance):
        _fail("training_context_mismatch")
    result, calls = archive.get("result"), archive.get("provider_calls")
    if (not isinstance(result, dict) or result.get("harness2_revision") != HARNESS2_REVISION
            or result.get("executor") != "opencode" or result.get("budget") != manifest.get("budget")
            or not isinstance(calls, list) or len(calls) != 8
            or sum(row.get("kind") == "probe" for row in calls) != 4
            or sum(row.get("kind") == "editor" for row in calls) != 4):
        _fail("search_execution_proof_invalid")
    expected_used = 4 * PROBE_CALL_LIMIT + 4
    if result["budget"] != {"limit": HARNESS2_MAX_MODEL_CALLS - 2, "used_upper_bound": expected_used}:
        _fail("original_search_budget_mismatch")
    rows = result.get("results")
    content = rows[0].get("candidate") if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict) else None
    if not isinstance(content, str):
        _fail("archived_candidate_required")
    try:
        permitted = replace_procedure(baseline_content, content.split(EDIT_START)[1].split(EDIT_END)[0].strip())
    except (ValueError, IndexError, ModelError):
        _fail("candidate_authority_or_noop_invalid")
    if content != permitted:
        _fail("candidate_authority_changed")
    used = expected_used + 2
    if used + 2 * len(suite.cases) * actor.max_iterations > HARNESS2_MAX_MODEL_CALLS:
        _fail("remaining_original_budget_insufficient")
    if validate_only:
        return {"status": "validated_read_only", "attempt_id": attempt_id,
                "candidate_sha256": _sha(content), "baseline_sha256": baseline["content_sha256"],
                "suite_manifest_sha256": attempt["suite_manifest_sha256"],
                "model": actor.config.model, "original_limit": HARNESS2_MAX_MODEL_CALLS,
                "used_upper_bound": used, "maximum_remaining_evaluation_calls": 2 * len(suite.cases) * actor.max_iterations,
                "continuation_claimed": False, "model_calls": 0}
    # Existing trace-key uniqueness is an atomic one-shot claim. A new nonce on
    # every invocation makes an existing key a conflict, never a success replay.
    continuation = await tools.call("record_trace", {
        "event_type": "improvement_continuation_started",
        "idempotency_key": f"improvement:{attempt_id}:continue-post-search",
        "payload": {"attempt_id": attempt_id, "nonce": str(uuid4()), "phase": "after_archived_search_before_evaluation",
                    "original_job_status": "failed", "archive_receipt": archive_receipt,
                    "candidate_sha256": _sha(content), "baseline_sha256": baseline["content_sha256"],
                    "suite_manifest_sha256": attempt["suite_manifest_sha256"],
                    "used_upper_bound_before_continuation": used, "original_max_model_calls": HARNESS2_MAX_MODEL_CALLS,
                    "new_search_calls": 0, "new_attempt_claim": False},
    })
    generated = {"output": {"rationale": "Continue the exact already archived Harness2 selection; no new generation.", "trace_references": [trace["id"]]},
                 "evidence": {"method": "harness2", "harness2_revision": HARNESS2_REVISION, "executor": "opencode",
                              "training_context_artifact": manifest["training_context_artifact"], "search_artifact": archive_receipt,
                              "budget": result["budget"], "provider_calls": calls, "continuation_receipt": continuation}}
    evidence = {"attempt_id": attempt_id, "suite_id": suite.suite_id, "status": "continuing", "rows": [],
                "model_call_budget": {"limit": HARNESS2_MAX_MODEL_CALLS, "used_upper_bound": used},
                "output_contract": OUTPUT_CONTRACT, "evaluator_version": EVALUATOR_VERSION, "gate_version": GATE_VERSION,
                "provider_usage": [], "improvement_method": "harness2", "attempt_claim": {"claimed": True, "existing_claim": True},
                "suite_manifest_sha256": attempt["suite_manifest_sha256"], "frozen_inputs_artifact": inputs,
                "triage": traces["flagged"].get("triage"), "diagnosis": traces["diagnosed"], "continuation_receipt": continuation}
    phase = _AttemptState(wrapped, attempt_id, evidence, HARNESS2_MAX_MODEL_CALLS)
    phase.usage("triage", traces["flagged"].get("triage", {}))
    phase.usage("diagnosis", traces["diagnosed"])
    for row in calls:
        phase.usage("search:" + row["kind"], row)
    # Same method as normal execution, including every quality/holdout/CAS gate.
    return await ImprovementEngine(actor, None, None)._evaluate_selected(
        phase=phase, baseline=baseline, baseline_content=baseline_content, suite=suite,
        content=content, generated=generated, fixed_context=fixed,
        manifest_hash=attempt["suite_manifest_sha256"], inputs=inputs, started=started,
    )

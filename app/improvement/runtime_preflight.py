"""Trusted, development-only runtime rehearsal before a fresh learning study.

This is not a promotion evaluator. It never opens the new promotion dataset,
changes a skill, retries a failed invocation, or calls the editor. Hosted callers
must schedule it on a quiet host; ordinary run inference reservations still apply.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid5

from app.improvement.dataset import FinanceDataset
from app.improvement.engine import EVALUATOR_VERSION, GATE_VERSION, READ_TOOLS
from app.improvement.harness2_search import HARNESS2_REVISION
from app.models import ModelConfig, ModelError
from app.runtime.decision_contract import OUTPUT_CONTRACT, validate_decision_shape
from app.runtime.failure_intake import private_failure_artifact
from app.runtime.opencode import PIN, OpenCodeActor

PREFLIGHT_CASES = ("fc-001", "fc-002")
PREFLIGHT_MODEL = "claude-sonnet-5-5"
PREFLIGHT_TOKENS = 8192
PREFLIGHT_CALLS = 8
PROVIDER_TIMEOUT = 90
ACTOR_TIMEOUT = 240
PROTOCOL = "finney-learning-runtime-preflight-v1"


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def learning_actor(config: ModelConfig, *, binary: Path | None = None) -> OpenCodeActor:
    """One explicit configuration for new-model baseline, search and candidate."""
    if config.model != PREFLIGHT_MODEL or config.api_mode != "anthropic_messages":
        raise ModelError("learning_preflight_model_mismatch")
    return OpenCodeActor(
        replace(config, max_tokens=PREFLIGHT_TOKENS, timeout_seconds=PROVIDER_TIMEOUT),
        binary=binary, max_iterations=PREFLIGHT_CALLS, timeout_seconds=ACTOR_TIMEOUT,
    )


def runtime_binding(actor: OpenCodeActor, *, baseline_content: str, fixed_context: dict) -> dict:
    """No credentials or protected cases are serialized into the binding."""
    if (not isinstance(actor, OpenCodeActor) or actor.mode != "finance"
            or actor.config.model != PREFLIGHT_MODEL
            or actor.config.api_mode != "anthropic_messages"
            or actor.config.max_tokens != PREFLIGHT_TOKENS
            or actor.config.timeout_seconds != PROVIDER_TIMEOUT
            or actor.max_iterations != PREFLIGHT_CALLS or actor.timeout_seconds != ACTOR_TIMEOUT):
        raise ModelError("learning_preflight_configuration_mismatch")
    if (not isinstance(fixed_context, dict) or set(fixed_context) != {"prefix", "suffix", "active_skill_sha256"}
            or not all(isinstance(value, str) for value in fixed_context.values())
            or not isinstance(baseline_content, str) or not baseline_content.strip()
            or fixed_context["active_skill_sha256"] != _hash(baseline_content)):
        raise ModelError("learning_preflight_context_required")
    return {
        "model": actor.config.model, "base_url": actor.config.base_url,
        "api_mode": actor.config.api_mode, "max_tokens": actor.config.max_tokens,
        "max_iterations": actor.max_iterations,
        "provider_timeout_seconds": actor.config.timeout_seconds,
        "actor_timeout_seconds": actor.timeout_seconds,
        "request_policy": {
            "thinking": {"type": "between_tools"}, "output_config": {"effort": "high"},
            "temperature": "omitted", "top_p": "omitted", "top_k": "omitted",
            "forced_tool_choice": "converted_to_auto", "structured_output_retry_count": 0,
        },
        "learning_roles": {"reviewer": {"max_tokens": PREFLIGHT_TOKENS, "timeout_seconds": PROVIDER_TIMEOUT},
                           "editor": {"max_tokens": PREFLIGHT_TOKENS, "provider_timeout_seconds": PROVIDER_TIMEOUT,
                                      "actor_timeout_seconds": 150, "max_iterations": 1}},
        # Request settings above describe the effective bridge payload, not the
        # SDK defaults. Bind actual implementation bytes against later drift.
        "implementation_sha256": {
            relative: hashlib.sha256((Path(__file__).parents[1] / relative).read_bytes()).hexdigest()
            for relative in ("runtime/opencode.py", "runtime/opencode_bridge.py", "runtime/opencode_editor.py",
                             "runtime/jobs.py", "models/providers.py",
                             "runtime/decision_contract.py", "runtime/tool_schemas.py",
                             "improvement/engine.py", "improvement/dataset.py",
                             "improvement/runtime_preflight.py", "improvement/harness2_candidate.py",
                             "improvement/harness2_search.py", "improvement/promotion_suite.py")
        },
        "opencode_revision": PIN["revision"], "opencode_version": PIN["version"],
        "harness2_revision": HARNESS2_REVISION,
        "baseline_sha256": _hash(baseline_content),
        "fixed_context_sha256": _hash(_json(fixed_context)),
        "output_contract": OUTPUT_CONTRACT, "evaluator_version": EVALUATOR_VERSION,
        "gate_version": GATE_VERSION,
    }


async def _save(tools, study: str, name: str, body: dict) -> dict:
    content = _json(body)
    receipt = await tools.call("put_artifact", {
        "name": f"runtime-preflight-{study}-{name}.json", "content": content,
        "content_type": "application/json", "idempotency_key": f"preflight:{study}:{name}",
    })
    if receipt.get("content_sha256") != _hash(content) or not receipt.get("artifact_path"):
        raise ModelError("learning_preflight_artifact_mismatch")
    return {"artifact_path": receipt["artifact_path"], "content_sha256": receipt["content_sha256"]}


async def run_runtime_preflight(*, actor: OpenCodeActor, tools, study_id: str,
                                baseline_content: str, fixed_context: dict) -> dict:
    """Two real baseline invocations, at most sixteen calls; no retry or promotion.

    Financial correctness is scored independently and never used as an excuse to
    label a failed runtime successful. Conversely a financially wrong, completed
    answer is useful baseline evidence rather than a broken testing environment.
    The same study UUID cannot reserve inference twice, including after a crash.
    """
    study = str(UUID(study_id))
    binding = runtime_binding(actor, baseline_content=baseline_content, fixed_context=fixed_context)
    dataset = FinanceDataset(evaluator=True, allow_heldout=False)
    if not set(PREFLIGHT_CASES) <= set(dataset.case_ids("development")):
        raise ModelError("learning_preflight_development_cases_required")
    snapshots = {cid: dataset.snapshot(cid, tools.scope) for cid in PREFLIGHT_CASES}
    for snapshot in snapshots.values():
        if not getattr(tools.for_evaluation(snapshot), "prepare_only", False):
            raise ModelError("evaluation_tools_not_prepare_only")
    protocol = {
        "contract": PROTOCOL, "study_id": study, "binding": binding,
        "scope": {"organization_id": str(tools.scope.organization_id), "run_id": str(tools.scope.run_id)},
        "dataset_sha256": dataset.manifest_sha256, "case_ids": list(PREFLIGHT_CASES),
        "snapshot_sha256": {cid: _hash(_json(snapshot)) for cid, snapshot in snapshots.items()},
        "policy_sha256": {cid: _hash(_json(snapshot["immutable_policy"]))
                          for cid, snapshot in snapshots.items()},
        "max_reserved_calls": len(PREFLIGHT_CASES) * PREFLIGHT_CALLS,
        "retry_policy": "none", "activation": "not_performed", "final_holdout_opened": False,
    }
    frozen = await _save(tools, study, "protocol", protocol)
    reservation = str(uuid5(UUID(study), "runtime-preflight"))
    claimed = await tools.call("reserve_run_inference", {
        "reservation_id": reservation, "job_id": None,
        "max_model_calls": protocol["max_reserved_calls"], "purpose": "learning-benchmark",
        "idempotency_key": f"preflight-reserve:{reservation}",
    })
    if claimed.get("claimed") is not True:
        raise ModelError("learning_preflight_reservation_denied")
    summary = {**protocol, "protocol_artifact": frozen, "status": "running", "rows": [],
               "reservation_id": reservation, "api_calls_observed": 0}
    skill = fixed_context["prefix"] + baseline_content + fixed_context["suffix"]
    for cid, snapshot in snapshots.items():
        result = None
        try:
            result = await actor.run(
                {"case": copy.deepcopy(snapshot), "mode": "prepare_only"}, skill,
                tools.for_evaluation(snapshot), allowed_tools=READ_TOOLS,
                policy=copy.deepcopy(snapshot["immutable_policy"]), max_model_calls=PREFLIGHT_CALLS,
            )
            validate_decision_shape(result["output"])
            evidence = result["evidence"]
            if (evidence.get("model") != binding["model"]
                    or evidence.get("runtime") != "opencode"
                    or evidence.get("revision") != PIN["revision"]
                    or type(evidence.get("api_calls")) is not int
                    or not 1 <= evidence["api_calls"] <= PREFLIGHT_CALLS):
                raise ModelError("learning_preflight_evidence_invalid")
        except (ModelError, ValueError, TypeError, KeyError) as error:
            diagnostic = getattr(error, "private_diagnostic", None)
            if diagnostic is None and result is not None:
                diagnostic = {"returned_result": result}
            row = {"case_id": cid, "runtime_valid": False, "financial_correct": None,
                   "reason": error.code if isinstance(error, ModelError) else "invalid_actor_result",
                   "diagnostic_status": "not_supplied"}
            if isinstance(diagnostic, dict):
                try:
                    row["diagnostic_artifact"] = await _save(
                        tools, study, cid + "-failure", json.loads(private_failure_artifact(diagnostic)),
                    )
                    row["diagnostic_status"] = "persisted"
                except Exception:  # noqa: BLE001 -- preserve the original failure, without exception text.
                    row["diagnostic_status"] = "unavailable"
            summary["rows"].append(row)
            summary["status"] = "blocked"
            break
        try:
            score = await dataset.score_case(cid, result, tools)
        except Exception:  # noqa: BLE001 -- scorer failure is not model evidence or a successful preflight.
            artifact = await _save(tools, study, cid + "-result", {"result": result, "scoring_status": "failed"})
            summary["rows"].append({"case_id": cid, "runtime_valid": True,
                                    "financial_correct": None, "reason": "preflight_scoring_failed",
                                    "result_artifact": artifact})
            summary["status"] = "blocked"
            break
        artifact = await _save(tools, study, cid + "-result", {"result": result, "score": score})
        summary["api_calls_observed"] += evidence["api_calls"]
        summary["rows"].append({
            "case_id": cid, "runtime_valid": True, "financial_correct": score["passed"],
            "hard_invariants_passed": score["hard_invariants_passed"], "result_artifact": artifact,
            "api_calls": evidence["api_calls"],
        })
    if summary["status"] == "running":
        summary["status"] = "runtime_ready"
    receipt = await _save(tools, study, "summary", summary)
    return {**summary, "summary_artifact": receipt}


async def require_runtime_preflight(*, tools, receipt: dict, actor: OpenCodeActor,
                                    baseline_content: str, fixed_context: dict) -> dict:
    """Load the private completion receipt and bind the next study to its runtime."""
    stored = await tools.call("read_artifact", {"artifact_path": receipt["artifact_path"]})
    content = stored.get("content")
    if not isinstance(content, str) or _hash(content) != receipt.get("content_sha256"):
        raise ModelError("learning_preflight_receipt_mismatch")
    body = json.loads(content)
    binding = runtime_binding(actor, baseline_content=baseline_content, fixed_context=fixed_context)
    rows = body.get("rows", [])
    if (body.get("contract") != PROTOCOL or body.get("status") != "runtime_ready"
            or body.get("binding") != binding or body.get("case_ids") != list(PREFLIGHT_CASES)
            or body.get("scope") != {"organization_id": str(tools.scope.organization_id),
                                     "run_id": str(tools.scope.run_id)}
            or [row.get("case_id") for row in rows] != list(PREFLIGHT_CASES)
            or not all(row.get("runtime_valid") is True and row.get("result_artifact") for row in rows)
            or body.get("final_holdout_opened") is not False):
        raise ModelError("learning_preflight_not_ready_or_drifted")
    return body

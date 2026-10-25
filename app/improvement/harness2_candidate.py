"""Online Harness2 candidate search from a captured trace, with no answer-key access."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path

from app.models import ModelError
from app.runtime.failure_intake import failure_observations, private_failure_artifact
from app.runtime.hermes import HermesActorError
from app.runtime.opencode import OpenCodeActor

from .engine import EDIT_END, EDIT_START, READ_TOOLS, replace_procedure
from .harness2_search import SearchBudget, run_harness_search

PROBE_CALL_LIMIT = 6
MAX_TRAINING_BYTES = 512_000
MAX_SEARCH_ARTIFACT_BYTES = 8_000_000  # Serialized bytes, below the Storage tool's 10 MiB limit.


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def persist_search_artifacts(
    root: Path, tools: object, frozen_receipt: dict, result: dict, calls: list
) -> dict:
    """Persist complete evidence as byte-bounded JSON parts and a small manifest."""
    parts, batch = [], []

    async def flush():
        if not batch:
            return
        content = _json({"contract": "finney-harness2-artifact-part-v1", "records": batch})
        if len(content.encode()) > MAX_SEARCH_ARTIFACT_BYTES:
            raise ModelError("harness2_search_artifact_too_large")
        parts.append(
            await tools.call(
                "put_artifact",
                {
                    "name": f"harness2-search-part-{len(parts):04}.json",
                    "content": content,
                    "content_type": "application/json",
                },
            )
        )
        batch.clear()

    files = {"__search_result__.json": _json({"result": result, "provider_calls": calls})}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ModelError("harness2_search_artifact_invalid")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path.read_text()
    chunk_chars = min(100_000, MAX_SEARCH_ARTIFACT_BYTES // 16)
    for name, text in files.items():
        chunks = [text[i : i + chunk_chars] for i in range(0, len(text), chunk_chars)] or [""]
        for index, chunk in enumerate(chunks):
            row = {
                "path": name,
                "chunk_index": index,
                "chunk_count": len(chunks),
                "file_sha256": _sha(text),
                "text": chunk,
            }
            candidate = _json(
                {"contract": "finney-harness2-artifact-part-v1", "records": [*batch, row]}
            )
            if len(candidate.encode()) > MAX_SEARCH_ARTIFACT_BYTES:
                await flush()
            batch.append(row)
    await flush()
    content = _json(
        {
            "contract": "finney-harness2-artifact-manifest-v1",
            "training_context_artifact": frozen_receipt,
            "parts": parts,
            "method": result.get("method"),
            "status": result.get("status", "selected"),
            "harness2_revision": result.get("harness2_revision"),
            "budget": result.get("budget"),
        }
    )
    if len(content.encode()) > MAX_SEARCH_ARTIFACT_BYTES:
        raise ModelError("harness2_search_artifact_too_large")
    return await tools.call(
        "put_artifact",
        {
            "name": "harness2-online-search.json",
            "content": content,
            "content_type": "application/json",
        },
    )


async def captured_training_snapshot(trace: dict, tools: object) -> tuple[dict, dict]:
    """Reconstruct only observed reads. Missing observations remain unavailable.

    No current database/source read repairs a historical snapshot. Raw failed
    output is not an expected answer and is never admitted to the search packet.
    """
    if not hasattr(tools, "for_evaluation") or not hasattr(tools, "scope"):
        raise ModelError("harness2_prepare_only_tools_required")
    events = trace.get("tool_events")
    diagnostic_receipt = None
    if trace.get("actor_status") == "failed":
        diagnostic_receipt = trace.get("diagnostic_artifact", {})
        if not isinstance(diagnostic_receipt, dict) or not diagnostic_receipt.get("artifact_path"):
            raise ModelError("harness2_training_diagnostic_required")
        artifact = await tools.call(
            "read_artifact", {"artifact_path": diagnostic_receipt["artifact_path"]}
        )
        content = artifact.get("content")
        if not isinstance(content, str) or _sha(content) != diagnostic_receipt.get(
            "content_sha256"
        ):
            raise ModelError("harness2_training_diagnostic_hash_mismatch")
        try:
            diagnostic = json.loads(content)
        except (ValueError, TypeError):
            raise ModelError("harness2_training_diagnostic_invalid") from None
        if not isinstance(diagnostic, dict) or diagnostic.get("truncated"):
            raise ModelError("harness2_training_diagnostic_incomplete")
        events = diagnostic.get("tool_events")
    if not isinstance(events, list) or len(events) > 64:
        raise ModelError("harness2_training_observations_required")
    snapshot = {
        "organization": {"id": str(tools.scope.organization_id)},
        "run": {"id": str(tools.scope.run_id)},
    }
    cases, documents = {}, {}
    for event in events:
        if not isinstance(event, dict):
            raise ModelError("harness2_training_observations_invalid")
        name, result = event.get("name"), event.get("result")
        if isinstance(result, dict) and result.get("status") in {"blocked", "failed"}:
            continue
        if name == "get_case" and isinstance(result, dict) and isinstance(result.get("id"), str):
            cases[result["id"]] = copy.deepcopy(result)
        elif name == "read_document" and isinstance(result, dict):
            doc = copy.deepcopy(result)
            doc.setdefault("id", event.get("arguments", {}).get("source_id"))
            if isinstance(doc.get("id"), str) and isinstance(doc.get("content"), str):
                if type(doc.get("version")) is not int or doc["version"] < 1:
                    raise ModelError("harness2_training_source_version_required")
                identity = (doc["id"], doc["version"])
                if identity in documents and documents[identity] != doc:
                    raise ModelError("harness2_training_source_conflict")
                documents[identity] = doc
        elif name == "get_obligations" and isinstance(result, list):
            snapshot["obligations"] = copy.deepcopy(result)
        elif name == "get_budget_plan" and isinstance(result, dict):
            snapshot["budget"] = copy.deepcopy(result)
        elif name == "get_financial_position" and isinstance(result, dict):
            snapshot["position"] = copy.deepcopy(result)
    provenance = trace.get("case_provenance")
    if isinstance(provenance, dict) and provenance.get("id"):
        selected = cases.get(provenance["id"])
        if selected is None or selected.get("version") != provenance.get("version"):
            raise ModelError("harness2_training_case_version_mismatch")
        cases = {selected["id"]: selected}
    if len(cases) != 1 or not documents:
        raise ModelError("harness2_training_case_and_sources_required")
    snapshot["cases"], snapshot["source_items"] = list(cases.values()), list(documents.values())
    if len(_json(snapshot).encode()) > MAX_TRAINING_BYTES:
        raise ModelError("harness2_training_snapshot_too_large")
    provenance = {
        "source_trace_id": trace.get("id"),
        "snapshot_sha256": _sha(_json(snapshot)),
        "diagnostic_artifact": copy.deepcopy(diagnostic_receipt),
        "source_refs": [{"id": doc["id"], "version": doc["version"]} for doc in documents.values()],
        "missing_observations": [
            name for name in ("obligations", "budget", "position") if name not in snapshot
        ],
    }
    return snapshot, provenance


def make_harness2_candidate_search(actor: OpenCodeActor, model: object):
    """Factory owned by the trusted worker; no evaluator or protected suite captured."""
    if not isinstance(actor, OpenCodeActor):
        raise ModelError("harness2_requires_opencode_actor")

    async def search(
        *,
        trace: dict,
        baseline_content: str,
        tools: object,
        fixed_context: dict | None,
        policy: dict | None,
        reserve_calls,
        remaining_budget: int,
    ) -> dict:
        probe_limit = min(actor.max_iterations, PROBE_CALL_LIMIT)
        # k=1 has four probes and four editor/reflect calls in the pinned schedule.
        # Check the entire bounded search before the first provider can run.
        required = 4 * probe_limit + 4
        if type(remaining_budget) is not int or remaining_budget < required:
            raise ModelError("harness2_search_budget_exhausted")
        snapshot, provenance = await captured_training_snapshot(copy.deepcopy(trace), tools)
        fixed = copy.deepcopy(fixed_context)
        policy = copy.deepcopy(policy)
        frozen = {
            "contract": "finney-harness2-training-v1",
            "snapshot": snapshot,
            "provenance": provenance,
            "immutable_runtime_context": fixed,
            "immutable_policy": policy,
            "baseline_sha256": _sha(baseline_content),
        }
        frozen_content = _json(frozen)
        frozen_receipt = await tools.call(
            "put_artifact",
            {
                "name": "harness2-training-context.json",
                "content": frozen_content,
                "content_type": "application/json",
            },
        )
        if frozen_receipt.get("content_sha256") != _sha(frozen_content):
            raise ModelError("harness2_training_artifact_hash_mismatch")
        budget, calls = SearchBudget(remaining_budget), []
        # Only captured public inputs and immutable instructions reach Harness2.
        packets = {
            "captured-finance-case": {
                "task": "Investigate the captured finance case from its source evidence. Prepare only; "
                "state the supported next step and uncertainty without approving or executing payment.",
                "context": snapshot,
                "immutable_policy": policy,
                "immutable_runtime_context": fixed,
                "observed_failure": copy.deepcopy(trace.get("failure_observations")),
            }
        }

        async def before_editor(label):
            reserve_calls(1)

        async def on_editor(label, result):
            editor_receipt = await tools.call("put_artifact", {
                "name": "harness2-editor-" + hashlib.sha256(label.encode()).hexdigest()[:16] + ".json",
                "content": private_failure_artifact(result), "content_type": "application/json",
            })
            calls.append(
                {
                    "stage": label,
                    "kind": "editor",
                    "evidence": copy.deepcopy(result.get("evidence", {})),
                    "status": result.get("status", "completed"),
                    "error_code": result.get("error_code"),
                    "artifact": editor_receipt,
                }
            )

        async def execute(case_id, skill, run_id):
            budget.reserve(probe_limit)
            reserve_calls(probe_limit)
            scoped = tools.for_evaluation(copy.deepcopy(snapshot))
            if not getattr(scoped, "prepare_only", False):
                raise ModelError("evaluation_tools_not_prepare_only")
            try:
                result = await actor.run(
                    {"case": copy.deepcopy(snapshot), "mode": "prepare_only"},
                    fixed["prefix"] + skill + fixed["suffix"] if fixed else skill,
                    scoped,
                    allowed_tools=READ_TOOLS,
                    policy=copy.deepcopy(policy),
                    max_model_calls=probe_limit,
                )
                calls.append(
                    {
                        "stage": run_id,
                        "kind": "probe",
                        "evidence": copy.deepcopy(result.get("evidence", {})),
                    }
                )
                return {"status": "completed", **result}
            except HermesActorError as error:
                private = error.private_diagnostic
                receipt = await tools.call(
                    "put_artifact",
                    {
                        "name": "harness2-probe-failure-"
                        + hashlib.sha256(run_id.encode()).hexdigest()[:16]
                        + ".json",
                        "content": private_failure_artifact(private),
                        "content_type": "application/json",
                    },
                )
                calls.append(
                    {
                        "stage": run_id,
                        "kind": "probe",
                        "failure_code": error.code,
                        "api_calls": private.get("api_calls"),
                        "diagnostic_artifact": receipt,
                    }
                )
                return {
                    "status": "failed",
                    "error": error.code,
                    "output": None,
                    "tool_events": copy.deepcopy(private.get("tool_events", [])),
                    "failure_observations": failure_observations(error.code, private),
                }

        with tempfile.TemporaryDirectory(prefix="finney-harness2-online-") as directory:
            root = Path(directory)
            try:
                result = await run_harness_search(
                    root=root,
                    packets=packets,
                    baseline=baseline_content,
                    execute=execute,
                    model=model,
                    budget=budget,
                    before_editor=before_editor,
                    on_editor=on_editor,
                    mode="parallel",
                    k=1,
                )
            except Exception as error:  # noqa: BLE001 -- persist all generated artifacts, then safe failure.
                result = {"status": "failed", "error_type": type(error).__name__}
                failed = True
            else:
                failed = False
            artifact = await persist_search_artifacts(root, tools, frozen_receipt, result, calls)
        await tools.call(
            "record_trace",
            {
                "event_type": "harness2_candidate_search",
                "payload": {
                    "source_trace_id": trace.get("id"),
                    "status": "failed" if failed else "selected",
                    "training_context_artifact": frozen_receipt,
                    "search_artifact": artifact,
                    "budget": {"limit": budget.limit, "used_upper_bound": budget.used},
                    "activation": "not_requested",
                },
            },
        )
        if failed:
            raise ModelError("harness2_online_search_failed")
        rows = result.get("results", [])
        content = rows[0].get("candidate") if len(rows) == 1 else None
        if not isinstance(content, str):
            raise ModelError("candidate_harness2_no_selection")
        try:
            procedure = content.split(EDIT_START)[1].split(EDIT_END)[0].strip()
            permitted = replace_procedure(baseline_content, procedure)
        except (IndexError, AttributeError):
            raise ModelError("candidate_edit_outside_permitted_section") from None
        if content != permitted:
            raise ModelError("candidate_edit_outside_permitted_section")
        return {
            "content": content,
            "generation": {
                "output": {
                    "rationale": "Actual pinned Harness2 search; selection still requires independent paired evaluation.",
                    "trace_references": [trace.get("id")],
                },
                "evidence": {
                    "method": "harness2",
                    "harness2_revision": result["harness2_revision"],
                    "executor": "opencode",
                    "training_context_artifact": frozen_receipt,
                    "search_artifact": artifact,
                    "budget": result["budget"],
                    "provider_calls": calls,
                },
            },
        }

    return search

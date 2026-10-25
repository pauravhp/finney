from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.models import JevClient, ModelConfig, ModelError
from app.resources import resource_path

from .failure_intake import (
    ELIGIBLE_FAILURES,
    eligible_failed_trace,
    failed_improvement_request,
    failure_observations,
    private_failure_artifact,
    rejected_review_improvement_request,
)
from .hermes import FinanceTools, HermesActor
from .operation_policy import runtime_operation_policy
from .skills import runtime_skill_context

if TYPE_CHECKING:
    from app.config import Settings

DEFAULT_SKILL = resource_path("skills/finance/organizer-expenses.md")


def automatic_improvement_request(job: dict, outcome: dict, *, suite_id: str) -> dict | None:
    """A trusted scheduling hint, never a verdict or an inference authorization.

    The service checks operating review persistence first, then inserts this job using the
    trace-specific key. Atomic attempt/run-budget guards still execute before
    inference. A reviewer must establish a supported defect to generate a skill.
    """
    failed_request = failed_improvement_request(job, outcome, suite_id=suite_id)
    if failed_request is not None:
        return failed_request
    rejected_request = rejected_review_improvement_request(job, outcome, suite_id=suite_id)
    if rejected_request is not None:
        return rejected_request
    if (
        job.get("command_type") not in {"review_case", "director_message"}
        or outcome.get("status") != "completed"
        or outcome.get("triage", {}).get("status") != "completed"
        or not outcome.get("trace", {}).get("id")
        or not suite_id
        or outcome.get("improvement_eligible") is False
    ):
        return None
    trace_id = outcome["trace"]["id"]
    return {
        "payload": {"trace_id": trace_id, "suite_id": suite_id, "trigger": "completed_case_review"},
        "idempotency_key": f"improvement-review:{trace_id}",
    }


def improvement_review_request(job: dict) -> dict:
    payload = job.get("payload", {})
    if not isinstance(payload, dict) or set(payload) - {
        "trace_id",
        "suite_id",
        "feedback",
        "trigger",
    }:
        raise ModelError("improvement_payload_not_permitted")
    if not isinstance(payload.get("trace_id"), str) or not payload["trace_id"]:
        raise ModelError("completed_actor_trace_required")
    if not isinstance(payload.get("suite_id"), str) or not payload["suite_id"]:
        raise ModelError("protected_evaluation_suite_required")
    trigger = payload.get("trigger", "manual_review")
    feedback = payload.get("feedback")
    if trigger not in {"manual_review", "completed_case_review", "failed_case_review"} or (
        feedback is not None and (not isinstance(feedback, str) or not 1 <= len(feedback) <= 2000)
    ):
        raise ModelError("improvement_feedback_invalid")
    return {
        "trigger": trigger,
        "requested_by_user_id": job.get("requested_by"),
        "feedback": feedback,
        "feedback_is_untrusted_observation": True,
    }


async def ensure_baseline(tools: FinanceTools) -> dict:
    current = await tools.call("get_active_skill", {"skill_name": "organizer-expenses"})
    if current:
        return current
    content = DEFAULT_SKILL.read_text()
    artifact = await tools.call(
        "put_artifact",
        {
            "name": "organizer-expenses-baseline-v1.md",
            "content": content,
            "content_type": "text/markdown",
            "idempotency_key": "skill:organizer-expenses:baseline-v1:artifact",
        },
    )
    version = await tools.call(
        "save_skill_version",
        {
            "skill_name": "organizer-expenses",
            "version": "baseline-v1",
            **artifact,
            "status": "baseline",
            "metadata": {"origin": "bundled_initial_procedure", "learned": False},
            "idempotency_key": "skill:organizer-expenses:baseline-v1:version",
        },
    )
    await tools.call(
        "initialize_skill_baseline",
        {
            "skill_name": "organizer-expenses",
            "version_id": version["id"],
            "idempotency_key": "skill:organizer-expenses:baseline-v1:initialize",
        },
    )
    return {**version, **artifact, "skill_name": "organizer-expenses"}


async def run_job(
    job: dict, tools: FinanceTools, *, settings: Settings | None = None
) -> dict[str, Any]:
    """Worker contract: callers supply leased scope-bound tools, never browser roles."""
    command = job.get("command_type")
    if command not in {
        "intake",
        "review_case",
        "refresh_forecast",
        "generate_report",
        "evaluate_improvement",
        "director_message",
    }:
        return {"status": "blocked", "reason": "runtime_command_not_supported"}
    job_id = str(job.get("id", ""))
    if not job_id or not job.get("organization_id") or not job.get("run_id"):
        return {"status": "blocked", "reason": "job_scope_required"}
    failure_context = None
    try:
        from app.config import Settings

        settings = settings if settings is not None else Settings()
        config = ModelConfig.from_settings(settings)
        current = await ensure_baseline(tools)
        artifact = await tools.call("read_artifact", {"artifact_path": current["artifact_path"]})
        skill, skill_version = artifact["content"], current["id"]
        if current.get("content_sha256") != hashlib.sha256(skill.encode()).hexdigest():
            raise ModelError("active_skill_artifact_hash_mismatch")
        if settings.finance_actor_runtime == "opencode":
            from app.runtime.opencode import OpenCodeActor
            actor = OpenCodeActor(config, binary=settings.finance_opencode_binary or None)
        else:
            actor = HermesActor(
                config,
                source=Path(settings.finance_hermes_source) if settings.finance_hermes_source else None,
                python=settings.finance_hermes_python or None,
            )
        gateway_key = settings.ai_gateway_api_key.get_secret_value()
        if command == "evaluate_improvement":
            from app.improvement.engine import (
                HARNESS2_MAX_MODEL_CALLS,
                MAX_MODEL_CALLS,
                ImprovementEngine,
            )
            from app.improvement.suites import organizer_expense_suite

            request = improvement_review_request(job)
            payload = job["payload"]
            if not gateway_key:
                raise ModelError("jev_unconfigured")
            captured = await tools.call("get_trace", {"trace_id": payload["trace_id"]})
            if not captured or (
                captured.get("event_type") != "actor_completed"
                and not (captured.get("event_type") == "actor_failed"
                         and eligible_failed_trace(captured.get("payload", {})))
            ):
                raise ModelError("eligible_actor_trace_required")
            trace = {**captured["payload"], "id": captured["id"], "review_request": request}
            if trace.get("improvement_eligible") is False:
                raise ModelError("trace_outside_mutable_skill_family")
            if trace.get("skill_version") != skill_version:
                raise ModelError("trace_baseline_version_is_not_active")
            fixed_context = None
            observed_policy = None
            if trace.get("runtime_context_artifact"):
                context_artifact = await tools.call(
                    "read_artifact",
                    {"artifact_path": trace["runtime_context_artifact"]["artifact_path"]},
                )
                if (
                    hashlib.sha256(context_artifact["content"].encode()).hexdigest()
                    != trace["runtime_context_artifact"]["content_sha256"]
                ):
                    raise ModelError("runtime_context_artifact_hash_mismatch")
                try:
                    descriptor = json.loads(context_artifact["content"])
                    fixed_context = descriptor["fixed_context"]
                    observed_policy = descriptor.get("immutable_policy")
                    if observed_policy is not None and not isinstance(observed_policy, dict):
                        raise ModelError("runtime_policy_artifact_invalid")
                    reconstructed = fixed_context["prefix"] + skill + fixed_context["suffix"]
                    if (
                        hashlib.sha256(reconstructed.encode()).hexdigest()
                        != trace["context_sha256"]
                    ):
                        raise ModelError("runtime_context_artifact_hash_mismatch")
                except (KeyError, TypeError, ValueError):
                    raise ModelError("runtime_context_artifact_invalid") from None
            from app.improvement.corpus_online import CORPUS_ONLINE_SUITE_ID, CorpusEvaluationTools
            from app.improvement.promotion_suite import PROMOTION_SUITE_ID, PromotionEvaluationTools
            from app.models import GenerativeModel
            from app.runtime.trace_contract import trace_contract_signals
            if payload.get("suite_id") in {CORPUS_ONLINE_SUITE_ID, PROMOTION_SUITE_ID}:
                if settings.finance_improvement_method != "harness2":
                    raise ModelError("online_corpus_requires_harness2")
                adapter = PromotionEvaluationTools if payload.get("suite_id") == PROMOTION_SUITE_ID else CorpusEvaluationTools
                tools = adapter(tools, getattr(tools, "claim_corpus_holdout", None))
            suite = organizer_expense_suite(tools, payload.get("suite_id", ""))
            # Check only the policy and source versions actually available during
            # this trace. An evaluation suite cannot retroactively authorize the
            # operating decision, and later source changes cannot rewrite it.
            observed_sources = {}
            for event in trace.get("tool_events", []):
                if not isinstance(event, dict) or event.get("name") != "read_document":
                    continue
                source = event.get("result")
                if isinstance(source, dict) and isinstance(source.get("id"), str) and type(source.get("version")) is int:
                    observed_sources[source["id"]] = {"id": source["id"], "version": source["version"]}
            trace["contract_signals"] = trace_contract_signals(
                trace.get("output"), protected_policy=observed_policy,
                current_source_refs=list(observed_sources.values()) or None,
                captured_tool_events=trace.get("tool_events"),
            )
            trace["policy_provenance"] = {
                "status": "captured_runtime_context" if observed_policy is not None else "not_captured",
                "evaluation_policy_is_not_observed_policy": True,
            }
            reviewer = GenerativeModel(config)
            candidate_search = None
            if settings.finance_improvement_method == "harness2":
                from dataclasses import replace

                from app.improvement.harness2_candidate import make_harness2_candidate_search
                from app.runtime.opencode_editor import OpenCodeEditor
                if settings.finance_actor_runtime != "opencode":
                    raise ModelError("harness2_requires_opencode_actor")
                editor = OpenCodeEditor(replace(config, max_tokens=3500),
                                        binary=settings.finance_opencode_binary or None)
                candidate_search = make_harness2_candidate_search(actor, editor)
            engine = ImprovementEngine(
                actor, reviewer, JevClient(gateway_key),
                **({"candidate_search": candidate_search} if candidate_search else {}),
            )
            result = await engine.run(
                trace=trace,
                baseline=current,
                baseline_content=skill,
                suite=suite,
                tools=tools,
                attempt_id=job_id,
                fixed_context=fixed_context,
                observed_policy=observed_policy,
                max_model_calls=HARNESS2_MAX_MODEL_CALLS if candidate_search else MAX_MODEL_CALLS,
            )
            # Rejection is a completed evaluation outcome, not a fabricated success.
            return {
                "status": "blocked" if result["status"] == "blocked" else "completed",
                "improvement": result,
            }
        payload = job.get("payload", {})
        if not isinstance(payload, dict):
            raise ModelError("runtime_payload_invalid")
        if command == "director_message" and (
            not isinstance(payload.get("message"), str) or not 1 <= len(payload["message"]) <= 4000
        ):
            raise ModelError("director_message_invalid")
        case = None
        if command in {"review_case", "director_message"} and payload.get("case_id"):
            case = await tools.call("get_case", {"case_id": payload["case_id"]})
        context, routing, fixed_context = runtime_skill_context(
            command, payload, case, active_skill=current, active_content=skill
        )
        if command == "director_message":
            routing = {**routing, "improvement_eligible": False, "mutable_skill_name": None,
                       "response_contract": "finance-director-response-v1"}
        observed_policy = runtime_operation_policy()
        context_artifact = await tools.call(
            "put_artifact",
            {
                "name": f"runtime-context-{job_id}.json",
                "content": json.dumps(
                    {"routing": routing, "fixed_context": fixed_context, "immutable_policy": observed_policy}, sort_keys=True
                ),
                "content_type": "application/json",
                "idempotency_key": f"job:{job_id}:runtime-context",
            },
        )
        reservation = await tools.call(
            "reserve_run_inference",
            {
                "reservation_id": job_id,
                "max_model_calls": getattr(actor, "max_iterations", 8) + bool(gateway_key),
            },
        )
        if reservation.get("claimed") is not True:
            raise ModelError(reservation.get("reason", "run_inference_budget_not_reserved"))
        failure_context = {
            "job_id": job_id, "command_type": command,
            "initiated_by_user_id": job.get("requested_by"),
            "skill_version": skill_version if routing["improvement_eligible"]
            else "bundle:" + routing["context_sha256"],
            **routing, "runtime_context_artifact": context_artifact,
            "inference_reservation": reservation,
            "case_provenance": {"id": case.get("id"), "version": case.get("version")}
            if isinstance(case, dict) else None,
        }
        result = await actor.run({"command_type": command, "payload": payload}, context, tools, policy=observed_policy)
        diagnostic = result.pop("private_diagnostic", None)
        if diagnostic is not None:
            result["diagnostic_artifact"] = await tools.call("put_artifact", {
                "name": "actor-format-diagnostic.json", "content_type": "application/json",
                "content": json.dumps(diagnostic, sort_keys=True),
            })
        trace = {
            "job_id": job_id,
            "initiated_by_user_id": job.get("requested_by"),
            "skill_version": skill_version
            if routing["improvement_eligible"]
            else "bundle:" + routing["context_sha256"],
            **routing,
            "runtime_context_artifact": context_artifact,
            "inference_reservation": reservation,
            **result,
        }
        recorded = await tools.call(
            "record_trace",
            {
                "event_type": "actor_completed",
                "payload": trace,
                "idempotency_key": f"job:{job_id}:actor-trace",
            },
        )
        triage = {"status": "blocked", "reason": "jev_unconfigured"}
        if gateway_key:
            try:
                triage = {
                    "status": "completed",
                    **await JevClient(gateway_key).evaluate_trace(trace),
                }
            except ModelError as error:
                triage = {"status": "blocked", "reason": error.code}
            await tools.call(
                "record_trace",
                {
                    "event_type": "jev_triage",
                    "payload": triage,
                    "idempotency_key": f"job:{job_id}:jev-trace",
                },
            )
        return {"status": "completed", **result, **routing, "trace": recorded, "triage": triage}
    except ModelError as error:
        diagnostic_receipt = None
        observations = None
        eligible = False
        diagnostic = getattr(error, "private_diagnostic", None)
        if isinstance(diagnostic, dict) and failure_context is not None:
            try:
                artifact = await tools.call("put_artifact", {
                    "name": "actor-failed-diagnostic.json", "content_type": "application/json",
                    "content": private_failure_artifact(diagnostic),
                    "idempotency_key": f"job:{job_id}:failure-diagnostic",
                })
                observations = failure_observations(error.code, diagnostic)
                failed_payload = {
                    **failure_context, "reason": observations["reason"], "actor_status": "failed",
                    "diagnostic_artifact": artifact, "failure_observations": observations,
                }
                eligible = error.code in ELIGIBLE_FAILURES and eligible_failed_trace(failed_payload)
                failed_payload["improvement_eligible"] = eligible
                diagnostic_receipt = await tools.call("record_trace", {
                    "event_type": "actor_failed", "payload": failed_payload,
                    "idempotency_key": f"job:{job_id}:failure:{observations['reason']}",
                })
            except Exception as persistence_error:  # noqa: BLE001 -- retain primary safe failure.
                eligible = False
                diagnostic_receipt = {"status": "unavailable", "error_type": type(persistence_error).__name__}
        return {"status": "blocked", "reason": error.code, "provider_status": error.status,
                "improvement_eligible": eligible,
                **({"failure_observations": observations} if observations is not None else {}),
                **({"failure_trace": diagnostic_receipt} if diagnostic_receipt is not None else {})}
    except Exception as error:  # noqa: BLE001 -- job boundary reports a safe failure without provider bodies.
        return {
            "status": "failed",
            "reason": "runtime_dependency_or_persistence_failure",
            "error_type": type(error).__name__,
        }

"""Bounded, hosted-recorded OpenCode/Harness2 comparison against Hermes.

Actor execution and candidate search never receive the protected scoring key.
No financial side effects or activation occur in this comparison command.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

from app.config import Settings
from app.finance.tools import FinanceToolClient
from app.finance.types import Scope
from app.improvement.dataset import FinanceDataset
from app.improvement.engine import READ_TOOLS
from app.improvement.harness2_search import (
    SearchBudget,
    digest,
    run_harness_search,
    verify_harness2,
)
from app.models import GenerativeModel, ModelConfig, ModelError
from app.resources import resource_path
from app.runtime.hermes import HermesActor, HermesActorError
from app.storage.supabase import SupabaseClient


def gate(rows: list[dict], *, expected_ids, baseline="opencode", candidate="harness2", repetitions=2) -> dict:
    """Same-case paired release evidence; failed execution remains in denominator."""
    pairs = {}
    for row in rows:
        if row["variant"] not in {baseline, candidate}:
            continue
        key = row["case_id"], row["repetition"]
        pair = pairs.setdefault(key, {})
        if row["variant"] in pair:
            return {"passed": False, "reason": "duplicate_pair"}
        pair[row["variant"]] = row
    if not pairs or any(set(p) != {baseline, candidate} for p in pairs.values()):
        return {"passed": False, "reason": "incomplete_pairs"}
    cases = {key[0] for key in pairs}
    if cases != set(expected_ids):
        return {"passed": False, "reason": "case_set_mismatch"}
    if any({rep for cid, rep in pairs if cid == case} != set(range(repetitions)) for case in cases):
        return {"passed": False, "reason": "incomplete_repetitions"}
    b = [p[baseline] for p in pairs.values()]
    c = [p[candidate] for p in pairs.values()]
    metrics = {"case_count": len(cases), "repetitions": repetitions,
               "baseline_correct": sum(r["score"]["passed"] for r in b),
               "candidate_correct": sum(r["score"]["passed"] for r in c),
               "paired_attempts": len(pairs), "variability_measured": repetitions > 1}
    if any(not r["score"]["hard_invariants_passed"] for r in c):
        return {"passed": False, "reason": "candidate_hard_invariant_failure", **metrics}
    if any(p[baseline]["score"]["passed"] and not p[candidate]["score"]["passed"] for p in pairs.values()):
        return {"passed": False, "reason": "regression_on_previously_correct_attempt", **metrics}
    both = [p for p in pairs.values() if p[baseline]["score"]["passed"] and p[candidate]["score"]["passed"]]
    metrics["baseline_tool_calls_correct_pairs"] = sum(p[baseline]["tool_calls"] for p in both)
    metrics["candidate_tool_calls_correct_pairs"] = sum(p[candidate]["tool_calls"] for p in both)
    if metrics["candidate_correct"] > metrics["baseline_correct"]:
        return {"passed": True, "reason": "observed_correctness_gain", **metrics}
    if both and metrics["candidate_tool_calls_correct_pairs"] < metrics["baseline_tool_calls_correct_pairs"]:
        return {"passed": True, "reason": "equal_correctness_fewer_tool_calls", **metrics}
    return {"passed": False, "reason": "no_measured_improvement", **metrics}


class HostedExperiment:
    def __init__(self, *, tools, settings, dataset, root, experiment_id, call_limit=480, iterations=6):
        from app.runtime.opencode import OpenCodeActor
        self.tools, self.settings, self.dataset = tools, settings, dataset
        self.root, self.id = Path(root), experiment_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.budget = SearchBudget(call_limit)
        self.iterations = iterations
        self.config = replace(ModelConfig.from_settings(settings), max_tokens=2400, timeout_seconds=90)
        self.actors = {
            "hermes": HermesActor(self.config,
                                  source=Path(settings.finance_hermes_source) if settings.finance_hermes_source else None,
                                  python=settings.finance_hermes_python or None, max_iterations=iterations, timeout_seconds=180),
            "opencode": OpenCodeActor(self.config, binary=settings.finance_opencode_binary or None,
                                      max_iterations=iterations, timeout_seconds=180),
        }
        self.model = GenerativeModel(replace(self.config, max_tokens=3500))
        self.baseline = resource_path("skills/finance/organizer-expenses.md").read_text()
        self.guide = resource_path("skills/finance/runtime-guide.md").read_text()
        self.rows, self.receipts = [], []
        self.baseline_version = self.candidate_version = None
        self.evaluation_recorded = False

    async def evaluation_state(self, status, metrics, artifact_path=None):
        await self.tools.call("record_eval_run", {"id": self.id, "skill_name": "organizer-expenses",
            "baseline_version_id": self.baseline_version, "candidate_version_id": self.candidate_version,
            "status": status, "metrics": {"experiment_kind": "opencode-harness2-comparison",
                "evaluator_version": "finney-corpus-v1", "activation": "not_performed", **metrics},
            "artifact_path": artifact_path,
            "idempotency_key": f"learning-eval:{self.id}:{status}"})
        self.evaluation_recorded = True

    async def save(self, name, body):
        content = json.dumps(body, indent=2, default=str)
        key = hashlib.sha256((self.id + name).encode()).hexdigest()
        artifact = await self.tools.call("put_artifact", {"name": f"learning-{name}.json", "content": content,
            "content_type": "application/json", "idempotency_key": f"learning-artifact:{key}"})
        (self.root / f"{name}.json").write_text(content)
        self.receipts.append({"name": name, **artifact})
        return artifact

    async def reserve(self, name, count, *, local=True):
        if local:
            self.budget.reserve(count)
        reservation = str(UUID(hashlib.md5((self.id + name).encode()).hexdigest()))
        claimed = await self.tools.call("reserve_run_inference", {"reservation_id": reservation, "job_id": None,
            "max_model_calls": count, "purpose": "learning-benchmark",
            "idempotency_key": f"learning-reserve:{reservation}"})
        if claimed.get("claimed") is not True:
            raise ModelError(claimed.get("reason", "learning_reservation_denied"))

    async def execute(self, case_id, skill, run_name, variant="opencode"):
        await self.reserve(run_name, self.iterations)
        snapshot = self.dataset.snapshot(case_id, self.tools.scope)
        scoped = self.tools.for_evaluation(snapshot)
        actor = self.actors["hermes" if variant == "hermes" else "opencode"]
        try:
            result = await actor.run({"case": snapshot, "mode": "prepare_only"},
                self.guide + "\n\n" + skill, scoped,
                allowed_tools=READ_TOOLS | {"get_budget_plan"}, policy=snapshot["immutable_policy"],
                max_model_calls=self.iterations)
            result.setdefault("status", "completed")
        except HermesActorError as error:
            private = error.private_diagnostic
            # Private full failed trace is a durable artifact; failures are also
            # visible to search as bounded observations, never repaired decisions.
            await self.save("diagnostic-" + digest(run_name)[:20], private)
            result = {"status": "blocked", "error": error.code, "output": None,
                      "tool_events": private.get("tool_events", []),
                      "failure_observations": {"reason": error.code},
                      "evidence": {k: private.get(k) for k in ("api_calls", "usage")}}
        except ModelError as error:
            result = {"status": "blocked", "error": error.code, "output": None,
                      "tool_events": [], "evidence": {}}
        await self.save("run-" + digest(run_name)[:20], {"run": run_name, "case_id": case_id,
                        "variant": variant, "skill_sha256": hashlib.sha256(skill.encode()).hexdigest(),
                        "source_snapshot_sha256": digest(snapshot), "result": result})
        return result

    async def paired(self, ids, candidate, split, repetitions):
        for rep in range(repetitions):
            for case_id in ids:
                # Alternate order to avoid always giving one arm the warm path.
                variants = ("opencode", "harness2") if rep % 2 == 0 else ("harness2", "opencode")
                for variant in variants:
                    name = f"{split}-{case_id}-{rep}-{variant}"
                    result = await self.execute(case_id, candidate if variant == "harness2" else self.baseline, name, variant)
                    score = await self.dataset.score_case(case_id, result, self.tools)
                    row = {"case_id": case_id, "split": split, "repetition": rep, "variant": variant,
                           "score": score, "tool_calls": len(result.get("tool_events", [])),
                           "evidence": result.get("evidence", {}), "status": result["status"]}
                    self.rows.append(row)
                    await self.save("score-" + digest(name)[:20], row)
                    await self.tools.call("record_eval_result", {"eval_run_id": self.id,
                        "case_key": f"{split}:{case_id}:repeat-{rep+1}",
                        "variant": "baseline" if variant == "opencode" else "candidate",
                        "passed": score["passed"], "hard_invariants_passed": score["hard_invariants_passed"],
                        "metrics": {"tool_calls": row["tool_calls"], "api_calls": row["evidence"].get("api_calls")},
                        "details": {"group": split, "runtime": "opencode", "repetition": rep,
                            "errors": score.get("errors", []), "correctness_errors": score.get("correctness_errors", [])},
                        "idempotency_key": "learning-row:" + digest(self.id + name)})

    async def run(self, *, development_ids=None, repetitions=2):
        dev = development_ids or self.dataset.case_ids("development")[:2]
        validation = self.dataset.case_ids("validation")
        if any(cid not in self.dataset.case_ids("development") for cid in dev):
            raise ValueError("search restricted to development cases")
        frozen = {"experiment_id": self.id, "dataset_manifest": self.dataset.manifest,
            "development_ids": dev, "validation_ids": validation,
            "repetitions": repetitions, "actor_model": self.config.model,
            "actor_max_tokens": self.config.max_tokens, "actor_iterations": self.iterations,
            "editor_max_tokens": self.model.config.max_tokens, "call_limit": self.budget.limit,
            "harness2": verify_harness2(), "baseline_sha256": hashlib.sha256(self.baseline.encode()).hexdigest(),
            "source_kind": "source-informed synthetic corpus; no real customer records",
            "stopping_rule": "one fixed candidate, validation gate then untouched heldout; no answer edits or retries for a gain",
            "activation": "disabled", "effects_enabled": False}
        await self.save("frozen-plan", frozen)
        active = await self.tools.call("get_active_skill", {"skill_name": "organizer-expenses"})
        if active and active.get("content_sha256") == hashlib.sha256(self.baseline.encode()).hexdigest():
            self.baseline_version = active["id"]
        await self.tools.call("record_trace", {"event_type": "learning_experiment_started",
            "payload": {"experiment_id": self.id, "dataset_sha256": self.dataset.manifest["manifest_content_sha256"],
                        "validation_case_count": len(validation), "repetitions_per_variant": repetitions},
            "idempotency_key": f"learning-started:{self.id}"})
        # Matched-runtime smoke comparison on development only.
        for cid in dev:
            for variant in ("hermes", "opencode"):
                result = await self.execute(cid, self.baseline, f"runtime-{cid}-{variant}", variant)
                score = await self.dataset.score_case(cid, result, self.tools)
                self.rows.append({"case_id": cid, "split": "development", "repetition": 0,
                    "variant": variant, "score": score, "tool_calls": len(result.get("tool_events", [])),
                    "evidence": result.get("evidence", {}), "status": result["status"]})

        editor_sequence = 0
        async def before_editor(label):
            nonlocal editor_sequence
            editor_sequence += 1
            await self.reserve(f"editor-{editor_sequence}-{label}", 1, local=False)
        async def editor_result(label, generated):
            await self.save("editor-" + digest(label + str(len(self.receipts)))[:20], generated)
        search = await run_harness_search(root=self.root / "search",
            packets={cid: self.dataset.public_packet(cid) for cid in dev}, baseline=self.baseline,
            execute=self.execute, model=self.model, budget=self.budget, on_editor=editor_result,
            before_editor=before_editor)
        await self.save("search", search)
        candidate = search["results"][-1]["candidate"]
        if not candidate or candidate == self.baseline:
            return await self.finish("no_changed_candidate", search=search)
        # Candidate is fixed before any validation answers are consulted.
        await self.save("candidate", {"content": candidate, "sha256": hashlib.sha256(candidate.encode()).hexdigest()})
        artifact = await self.tools.call("put_artifact", {"name": f"organizer-expenses-harness2-{self.id}.md",
            "content": candidate, "content_type": "text/markdown", "idempotency_key": f"learning-skill-artifact:{self.id}"})
        version = await self.tools.call("save_skill_version", {"skill_name": "organizer-expenses",
            "version": "harness2-" + self.id, "artifact_path": artifact["artifact_path"],
            "content_sha256": artifact["content_sha256"], "parent_version_id": self.baseline_version,
            "status": "candidate", "metadata": {"method": "harness2", "experiment_id": self.id},
            "idempotency_key": f"learning-skill:{self.id}"})
        self.candidate_version = version["id"]
        await self.evaluation_state("candidate_created", {"candidate_sha256": artifact["content_sha256"]})
        await self.paired(validation, candidate, "validation", repetitions)
        verdict = gate([r for r in self.rows if r["split"] == "validation"],
                       expected_ids=validation, repetitions=repetitions)
        if not verdict["passed"]:
            return await self.finish("rejected_validation", validation=verdict)
        # One explicit final test phase. A second attempt needs a new untouched
        # dataset; a consumed marker is persisted before first final invocation.
        self.dataset = FinanceDataset(self.dataset.root, evaluator=True, allow_heldout=True)
        heldout = self.dataset.case_ids("heldout")
        claim = await self.tools._client.rpc("claim_finance_learning_holdout", {
            **self.tools.scope.params(), "p_experiment_id": self.id,
            "p_dataset_sha256": self.dataset.manifest["manifest_content_sha256"],
            "p_candidate_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
        })
        if claim.get("claimed") is not True:
            return await self.finish("blocked_consumed_holdout", validation=verdict)
        marker = await self.save("holdout-consumed", {"cases": heldout,
            "dataset_sha256": self.dataset.manifest["manifest_content_sha256"],
            "candidate_sha256": hashlib.sha256(candidate.encode()).hexdigest()})
        await self.paired(heldout, candidate, "heldout", repetitions)
        final_rows = [r for r in self.rows if r["split"] == "heldout"]
        transfer_pairs = {(r["case_id"], r["variant"], r["repetition"]) for r in final_rows}
        complete = transfer_pairs == {(cid, variant, rep) for cid in heldout
            for variant in ("opencode", "harness2") for rep in range(repetitions)}
        retained = complete and all(r["score"]["passed"] for r in final_rows if r["variant"] == "harness2")
        return await self.finish("validated_candidate" if retained else "rejected_transfer",
                                 validation=verdict, transfer_correct=retained, holdout_receipt=marker)

    async def finish(self, status, **details):
        library = self.root / "search" / "library"
        if library.exists():
            await self.save("experience-library", {p.relative_to(library).as_posix(): p.read_text()
                for p in library.rglob("*") if p.is_file() and not p.is_symlink()})
        summary = {"experiment_id": self.id, "status": status, "rows": self.rows,
                   "model_budget": {"limit": self.budget.limit, "reserved_upper_bound": self.budget.used},
                   "activation": "not_performed", "effects_enabled": False,
                   "claim": "bounded synthetic experiment; no production accuracy claim", **details}
        artifact = await self.save("summary", summary)
        await self.evaluation_state(status, {"model_budget": summary["model_budget"],
            "case_count": len({r["case_id"] for r in self.rows}),
            "measured_attempts": len(self.rows),
            **{k: v for k, v in details.items() if k != "search"}}, artifact["artifact_path"])
        await self.tools.call("record_trace", {"event_type": "learning_experiment_completed",
            "payload": {"experiment_id": self.id, "status": status, "artifact": artifact,
                        "activation": "not_performed", "effects_enabled": False},
            "idempotency_key": f"learning-completed:{self.id}"})
        return summary


async def _main(args):
    settings = Settings()
    if not args.live:
        raise SystemExit("Pass --live to run the bounded provider-backed experiment")
    scope = Scope(UUID(args.organization), UUID(args.run))
    experiment_id = str(uuid4())
    root = Path(args.output) / experiment_id
    async with SupabaseClient(settings.supabase_url, settings.backend_key) as db:
        tools = FinanceToolClient(scope, db)
        experiment = HostedExperiment(tools=tools, settings=settings,
            dataset=FinanceDataset(evaluator=True), root=root, experiment_id=experiment_id,
            call_limit=args.max_calls, iterations=args.iterations)
        try:
            summary = await experiment.run(development_ids=args.development_case, repetitions=args.repetitions)
        except Exception as error:
            await experiment.finish("blocked", error_code=getattr(error, "code", type(error).__name__))
            raise
        print(json.dumps({"experiment_id": experiment_id, "status": summary["status"],
                          "summary": str(root / "summary.json"), "activation": "not_performed"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--organization", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--output", default=".state/learning-experiments")
    parser.add_argument("--max-calls", type=int, default=480)
    parser.add_argument("--iterations", type=int, default=6)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--development-case", action="append", help="Development-only case IDs; repeat for multiple cases")
    args = parser.parse_args()
    if args.repetitions not in (1, 2, 3) or not 1 <= args.iterations <= 8:
        parser.error("repetitions 1–3 and iterations 1–8 required")
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()

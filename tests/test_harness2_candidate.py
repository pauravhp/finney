"""Online control-flow fixtures: actual Harness2, no model calls or real effects."""

import copy
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest
from pydantic import ValidationError
from test_improvement_lifecycle import (
    LifecycleActor,
    LifecycleJev,
    LifecyclePort,
    LifecycleReviewer,
)

from app.config import Settings
from app.finance.tools import FinanceToolClient
from app.finance.types import Scope
from app.improvement.blockers import BLOCKER_SUITE_ID
from app.improvement.engine import ImprovementEngine, replace_procedure
from app.improvement.harness2_candidate import (
    captured_training_snapshot,
    make_harness2_candidate_search,
    persist_search_artifacts,
)
from app.improvement.suites import organizer_expense_suite
from app.models import ModelConfig, ModelError
from app.runtime.jobs import DEFAULT_SKILL, ensure_baseline, run_job
from app.runtime.opencode import OpenCodeActor

PROCEDURE = "Unit lifecycle candidate: read each distinct current evidence document once and reuse the captured version when linking the payable."


class CapturedPort:
    def __init__(self):
        self.scope = Scope(UUID(int=1), UUID(int=2))
        self.finance = FinanceToolClient(self.scope, None)
        self.artifacts, self.saved, self.snapshots, self.traces = {}, [], [], []

    async def call(self, name, args):
        if name == "record_trace":
            assert isinstance(args.get("idempotency_key"), str) and 1 <= len(args["idempotency_key"]) <= 200
            self.traces.append(copy.deepcopy(args))
            return {"id": "unit-search-trace"}
        if name == "read_artifact":
            return {"content": self.artifacts[args["artifact_path"]]}
        assert name == "put_artifact", (
            "search may not read live records or protected evaluation inputs"
        )
        self.saved.append(copy.deepcopy(args))
        digest = hashlib.sha256(args["content"].encode()).hexdigest()
        path = "unit-private/" + digest
        self.artifacts[path] = args["content"]
        return {"artifact_path": path, "content_sha256": digest}

    def for_evaluation(self, snapshot):
        self.snapshots.append(copy.deepcopy(snapshot))
        return self.finance.for_evaluation(snapshot)


def source_trace():
    return {
        "id": str(UUID(int=9)),
        "tool_events": [
            {
                "name": "get_case",
                "arguments": {"case_id": "unit-case"},
                "result": {
                    "id": "unit-case",
                    "version": 2,
                    "title": "Review captured expense",
                    "source_ids": ["unit-source"],
                },
            },
            {
                "name": "read_document",
                "arguments": {"source_id": "unit-source"},
                "result": {
                    "id": "unit-source",
                    "version": 1,
                    "content": "Explicit synthetic captured source; no settlement claimed.",
                },
            },
            {"name": "get_obligations", "arguments": {}, "result": []},
        ],
    }


class FixtureOpenCode(OpenCodeActor):
    def __init__(self, port):
        self.config = ModelConfig("fixture-sonnet", "https://fixture.invalid/v1", "unit-secret")
        self.max_iterations, self.port, self.calls = 8, port, []

    async def run(self, prompt, skill, tools, **kwargs):
        assert self.port.saved[0]["name"] == "harness2-training-context.json"
        assert tools.prepare_only and kwargs["max_model_calls"] == 6
        assert "protected" not in json.dumps(prompt) and "expected" not in prompt
        self.calls.append((copy.deepcopy(prompt), skill, kwargs))
        documents = prompt["case"]["source_items"]
        document = await tools.call("read_document", {"source_id": documents[0]["id"]})
        return {
            "output": {
                "decision": "investigate",
                "explanation": "Fixture only.",
                "clarification": None,
                "proposed_action": None,
                "evidence_source_ids": [document["id"]],
                "blocking_requirements": [],
            },
            "tool_events": [{"name": "read_document", "arguments": {}, "result": document}],
            "evidence": {"api_calls": 1, "runtime": "opencode", "latency_seconds": 0.01},
        }


class FixtureEditor:
    config = SimpleNamespace(model="fixture-sonnet")

    def __init__(self):
        self.calls = []

    async def complete(self, system, prompt):
        payload = json.loads(prompt)
        assert not any("protected" in key for key in payload["files"])
        assert "UNSEEN_EXPECTED_SENTINEL" not in prompt
        self.calls.append(payload)
        return {
            "output": {
                "procedure": PROCEDURE,
                "notes": "Fixture only, independently grade next.",
                "edits": "Observed fixture contrast.",
                "experience": None,
            }
        }


@pytest.mark.asyncio
async def test_actual_harness2_online_search_freezes_observations_and_reserves_before_probes():
    port, editor = CapturedPort(), FixtureEditor()
    actor = FixtureOpenCode(port)
    reserved = []
    callback = make_harness2_candidate_search(actor, editor)
    result = await callback(
        trace=source_trace(),
        baseline_content=DEFAULT_SKILL.read_text(),
        tools=port,
        fixed_context=None,
        policy={"rules": []},
        reserve_calls=reserved.append,
        remaining_budget=94,
    )
    assert result["content"] == replace_procedure(DEFAULT_SKILL.read_text(), PROCEDURE)
    assert len(actor.calls) == 4 and len(editor.calls) == 4
    assert sorted(reserved) == [1, 1, 1, 1, 6, 6, 6, 6]
    assert result["generation"]["evidence"]["budget"]["used_upper_bound"] == 28
    assert all(
        s["source_items"][0]["content"] == source_trace()["tool_events"][1]["result"]["content"]
        for s in port.snapshots
    )
    stored = json.loads(port.saved[-1]["content"])
    assert stored["parts"] and stored["training_context_artifact"]
    assert "UNSEEN_EXPECTED_SENTINEL" not in json.dumps(stored)
    receipt_hash = result["generation"]["evidence"]["search_artifact"]["content_sha256"]
    assert port.traces[-1]["idempotency_key"] == f"harness2-search:{source_trace()['id']}:{receipt_hash}"


@pytest.mark.asyncio
async def test_serialized_search_parts_fit_storage_limit_and_reconstruct_escaped_unicode(tmp_path):
    text = '"\\\n😀' * 20_000
    (tmp_path / "evidence.md").write_text(text)
    port = CapturedPort()
    with patch("app.improvement.harness2_candidate.MAX_SEARCH_ARTIFACT_BYTES", 32_768):
        receipt = await persist_search_artifacts(
            tmp_path, port, {"artifact_path": "unit-frozen"}, {"method": "fixture"}, []
        )
    assert all(len(row["content"].encode()) <= 32_768 for row in port.saved)
    manifest = json.loads(port.artifacts[receipt["artifact_path"]])
    records = []
    for part in manifest["parts"]:
        records += json.loads(port.artifacts[part["artifact_path"]])["records"]
    chunks = sorted(
        (r for r in records if r["path"] == "evidence.md"), key=lambda r: r["chunk_index"]
    )
    assert len(chunks) == chunks[0]["chunk_count"]
    assert "".join(row["text"] for row in chunks) == text
    assert chunks[0]["file_sha256"] == hashlib.sha256(text.encode()).hexdigest()


@pytest.mark.asyncio
async def test_search_budget_rejection_precedes_any_provider_or_artifact():
    port, editor = CapturedPort(), FixtureEditor()
    actor = FixtureOpenCode(port)
    callback = make_harness2_candidate_search(actor, editor)
    with pytest.raises(ModelError, match="budget_exhausted"):
        await callback(
            trace=source_trace(),
            baseline_content=DEFAULT_SKILL.read_text(),
            tools=port,
            fixed_context=None,
            policy={},
            reserve_calls=lambda _: pytest.fail("no reservation"),
            remaining_budget=27,
        )
    assert actor.calls == editor.calls == port.saved == []


@pytest.mark.asyncio
async def test_failed_trace_hash_bound_diagnostic_supplies_reads_only():
    port = CapturedPort()
    diagnostic = json.dumps(
        {
            "tool_events": source_trace()["tool_events"],
            "original_final_response": "UNSEEN_EXPECTED_SENTINEL",
        }
    )
    path = "unit-private/diagnostic"
    port.artifacts[path] = diagnostic
    trace = {
        "id": "failed-unit",
        "actor_status": "failed",
        "case_provenance": {"id": "unit-case", "version": 2},
        "diagnostic_artifact": {
            "artifact_path": path,
            "content_sha256": hashlib.sha256(diagnostic.encode()).hexdigest(),
        },
    }
    snapshot, provenance = await captured_training_snapshot(trace, port)
    assert snapshot["cases"][0]["version"] == 2
    assert "UNSEEN_EXPECTED_SENTINEL" not in json.dumps(snapshot)
    assert "position" not in snapshot and "position" in provenance["missing_observations"]
    port.artifacts[path] += " "
    with pytest.raises(ModelError, match="hash_mismatch"):
        await captured_training_snapshot(trace, port)


@pytest.mark.asyncio
async def test_missing_training_sources_cannot_fall_back_to_live_snapshot():
    port = CapturedPort()
    with pytest.raises(ModelError, match="case_and_sources_required"):
        await captured_training_snapshot({"id": "unit", "tool_events": []}, port)


class LifecycleOpenCode(LifecycleActor, OpenCodeActor):
    pass


@pytest.mark.asyncio
async def test_engine_optional_search_receives_no_suite_and_uses_existing_pair_gate_and_cas():
    port = LifecyclePort()
    baseline = await ensure_baseline(port)
    suite = organizer_expense_suite(port, BLOCKER_SUITE_ID)
    actor, reviewer = LifecycleOpenCode(suite), LifecycleReviewer(port)
    seen = []

    async def search(**kwargs):
        seen.append(kwargs)
        assert set(kwargs) == {
            "trace",
            "baseline_content",
            "tools",
            "fixed_context",
            "policy",
            "reserve_calls",
            "remaining_budget",
        }
        assert "UNSEEN_EXPECTED_SENTINEL" not in json.dumps(
            {k: v for k, v in kwargs.items() if k not in {"tools", "reserve_calls"}}
        )
        kwargs["reserve_calls"](4)
        return {
            "content": replace_procedure(kwargs["baseline_content"], PROCEDURE),
            "generation": {"evidence": {"method": "harness2"}},
        }

    result = await ImprovementEngine(actor, reviewer, LifecycleJev(), candidate_search=search).run(
        trace={"id": "unit-observed", "output": {"explanation": "Observed duplicate reads."}},
        baseline=baseline,
        baseline_content=DEFAULT_SKILL.read_text(),
        suite=suite,
        tools=port,
        max_model_calls=96,
    )
    assert result["status"] == "promoted" and result["improvement_method"] == "harness2"
    assert len(seen) == 1 and len(reviewer.prompts) == 1
    claim = next(args for name, args in port.calls if name == "claim_improvement_attempt")
    assert claim["max_model_calls"] == 96 and claim["improvement_method"] == "harness2"
    assert len(result["rows"]) == 2 * len(suite.cases)
    assert any(name == "set_active_skill_version" for name, _ in port.calls)


@pytest.mark.asyncio
async def test_engine_reservation_rejection_never_invokes_model_or_search():
    class RejectedPort(LifecyclePort):
        async def call(self, name, args):
            if name == "claim_improvement_attempt":
                return {"claimed": False, "reason": "run_model_call_budget_exhausted"}
            return await super().call(name, args)

    port = RejectedPort()
    baseline = await ensure_baseline(port)
    suite = organizer_expense_suite(port, BLOCKER_SUITE_ID)
    actor, reviewer = LifecycleOpenCode(suite), LifecycleReviewer(port)

    async def never(**_):
        pytest.fail("search ran before budget claim")

    result = await ImprovementEngine(actor, reviewer, LifecycleJev(), candidate_search=never).run(
        trace={"id": "unit"},
        baseline=baseline,
        baseline_content=DEFAULT_SKILL.read_text(),
        suite=suite,
        tools=port,
        max_model_calls=96,
    )
    assert result["reason"] == "run_model_call_budget_exhausted"
    assert reviewer.prompts == [] and actor.loaded_skills == []


def test_settings_default_and_only_explicit_harness2_selection():
    assert Settings(_env_file=None).finance_improvement_method == "single_patch"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, finance_improvement_method="unbounded")
    with pytest.raises(ValidationError, match="requires"):
        Settings(
            _env_file=None, finance_improvement_method="harness2", finance_actor_runtime="hermes"
        )
    assert (
        Settings(
            _env_file=None, finance_improvement_method="harness2", finance_actor_runtime="opencode"
        ).finance_improvement_method
        == "harness2"
    )


@pytest.mark.asyncio
async def test_noop_search_keeps_receipts_and_does_not_fall_back_to_single_patch():
    class NoopEditor(FixtureEditor):
        async def complete(self, system, prompt):
            self.calls.append(json.loads(prompt))
            return {
                "output": {
                    "procedure": None,
                    "notes": "No supported edit.",
                    "edits": "No contrast.",
                    "experience": None,
                }
            }

    port, editor = CapturedPort(), NoopEditor()
    actor = FixtureOpenCode(port)
    callback = make_harness2_candidate_search(actor, editor)
    with pytest.raises(ModelError, match="candidate_no_op"):
        await callback(
            trace=source_trace(),
            baseline_content=DEFAULT_SKILL.read_text(),
            tools=port,
            fixed_context=None,
            policy={},
            reserve_calls=lambda _: None,
            remaining_budget=94,
        )
    assert len(editor.calls) == 4 and len(actor.calls) == 4
    assert any(row["name"] == "harness2-online-search.json" for row in port.saved)


@pytest.mark.asyncio
async def test_job_dispatch_picks_harness2_callback_and_96_call_allowance():
    port = LifecyclePort()
    baseline = await ensure_baseline(port)
    captured = await port.call(
        "record_trace",
        {
            "event_type": "actor_completed",
            "payload": {
                "skill_version": baseline["id"],
                "output": {"explanation": "Fixture observed behavior."},
            },
            "idempotency_key": "unit-dispatch",
        },
    )
    settings = Settings(
        _env_file=None,
        finance_actor_runtime="opencode",
        finance_improvement_method="harness2",
        finance_model_api_key="unit-config",
        ai_gateway_api_key="unit-config",
    )
    actor, callback, received = FixtureOpenCode(CapturedPort()), object(), []

    class Engine:
        def __init__(self, *args, **kwargs):
            assert args[0] is actor and kwargs["candidate_search"] is callback

        async def run(self, **kwargs):
            received.append(kwargs)
            return {"status": "rejected", "reason": "unit-only"}

    with (
        patch("app.runtime.opencode.OpenCodeActor", return_value=actor),
        patch(
            "app.improvement.harness2_candidate.make_harness2_candidate_search",
            return_value=callback,
        ),
        patch("app.improvement.engine.ImprovementEngine", Engine),
    ):
        result = await run_job(
            {
                "id": "unit-job",
                "organization_id": str(port.scope.organization_id),
                "run_id": str(port.scope.run_id),
                "command_type": "evaluate_improvement",
                "payload": {"trace_id": captured["id"], "suite_id": BLOCKER_SUITE_ID},
            },
            port,
            settings=settings,
        )
    assert result["status"] == "completed" and received[0]["max_model_calls"] == 96

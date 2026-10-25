"""Controlled interrupted-phase fixtures; PostgreSQL gates, no provider calls."""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_finance_postgres import database as database  # noqa: PLC0414
from test_finance_postgres import state as state  # noqa: PLC0414
from test_harness2_candidate import PROCEDURE, source_trace
from test_improvement_postgres import LocalPostgresWithFixtureArtifacts
from test_promotion_suite import oracle

from app.finance.tools import FinanceToolClient
from app.finance.types import Scope
from app.improvement.continuation import continue_archived_search
from app.improvement.decisions import EVALUATOR_VERSION
from app.improvement.engine import evaluation_manifest, replace_procedure
from app.improvement.harness2_candidate import captured_training_snapshot, persist_search_artifacts
from app.improvement.harness2_search import HARNESS2_REVISION
from app.improvement.promotion_suite import PROMOTION_SUITE_ID, PromotionDataset, promotion_suite
from app.models import ModelConfig, ModelError
from app.runtime.jobs import ensure_baseline
from app.runtime.opencode import OpenCodeActor
from app.runtime.operation_policy import runtime_operation_policy


class StorageWithMetadata(LocalPostgresWithFixtureArtifacts):
    async def upload(self, bucket, path, content, content_type):
        await super().upload(bucket, path, content, content_type)
        self.connection.execute("insert into storage.objects(id,name,bucket_id,created_at) values(%s,%s,%s,now())", (uuid4(), path, bucket))


class Tools:
    def __init__(self, finance, connection):
        self.finance, self.scope, self.connection = finance, finance.scope, connection
        self.calls = []

    async def call(self, name, args):
        self.calls.append((name, copy.deepcopy(args)))
        return await self.finance.call(name, args)

    def for_evaluation(self, snapshot):
        return self.finance.for_evaluation(snapshot)

    async def claim_corpus_holdout(self, *, experiment_id, dataset_sha256, candidate_sha256):
        return self.connection.execute("select claim_finance_learning_holdout(%s,%s,%s,%s,%s)",
            (self.scope.organization_id, self.scope.run_id, experiment_id, dataset_sha256, candidate_sha256)).fetchone()[0]


class Actor(OpenCodeActor):
    def __init__(self, suite, *, reject_transfer=False):
        self.suite, self.calls, self.reject_transfer = suite, [], reject_transfer
        self.config = ModelConfig("frozen-fixture-model", "https://fixture.invalid/v1", "fixture")
        self.max_iterations, self.binary = 8, Path("/unit-fixture-opencode")
        self.dataset = PromotionDataset(evaluator=True, allow_heldout=True)

    async def run(self, prompt, skill, tools, **kwargs):
        case = next(case for case in self.suite.cases if case.snapshot == prompt["case"])
        candidate = PROCEDURE in skill
        self.calls.append((case.group, candidate))
        value = oracle(self.dataset, case.case_key)
        if (case.group == "validation" and not candidate) or (self.reject_transfer and candidate and case.group == "transfer"):
            value["proposed_action"] = {"action": "investigate"}
        return {"output": value, "tool_events": [], "evidence": {"api_calls": 1, "latency_seconds": 0.01}}


async def prepared(state, tmp_path, monkeypatch):
    connection, org, run, _users = state
    connection.execute("reset role")  # Private preflight uses read-only coordinator privileges.
    connection.execute("alter table storage.objects add column if not exists created_at timestamptz")
    backend = StorageWithMetadata(connection)
    tools = Tools(FinanceToolClient(Scope(org, run), backend), connection)
    baseline = await ensure_baseline(tools)
    baseline_content = (await tools.call("read_artifact", {"artifact_path": baseline["artifact_path"]}))["content"]
    policy = runtime_operation_policy()
    fixed = {"prefix": "", "suffix": "", "active_skill_sha256": baseline["content_sha256"]}
    context = await tools.call("put_artifact", {"name": "runtime-context.json", "content": json.dumps({"fixed_context": fixed, "immutable_policy": policy})})
    trace = source_trace()
    trace.pop("id")
    trace.update(skill_version=baseline["id"], runtime_context_artifact=context, context_sha256=baseline["content_sha256"])
    captured = await tools.call("record_trace", {"event_type": "actor_completed", "payload": trace, "idempotency_key": "fixture-source"})
    trace["id"] = captured["id"]
    attempt = str(uuid4())
    connection.execute("insert into jobs(id,organization_id,run_id,command_type,payload,idempotency_key,status) values(%s,%s,%s,'evaluate_improvement',%s,%s,'running')",
        (attempt, org, run, Jsonb({"trace_id": trace["id"], "suite_id": PROMOTION_SUITE_ID}), "fixture-job"))
    suite = promotion_suite(tools)
    actor = Actor(suite)
    frozen = evaluation_manifest(actor, suite, fixed_context=fixed, observed_policy=policy, method="harness2")
    manifest_hash = hashlib.sha256(frozen.encode()).hexdigest()
    claimed = await tools.call("claim_improvement_attempt", {"attempt_id": attempt, "trace_id": trace["id"],
        "baseline_version_id": baseline["id"], "suite_id": PROMOTION_SUITE_ID, "suite_manifest_sha256": manifest_hash,
        "evaluator_version": EVALUATOR_VERSION, "max_model_calls": 96, "improvement_method": "harness2",
        "case_manifest": [{"case_key": c.case_key, "group": c.group, "source_snapshot_hash": c.source_snapshot_hash} for c in suite.cases]})
    assert claimed["claimed"]
    inputs = await tools.call("put_artifact", {"name": "frozen.json", "content": frozen})
    for name, payload in (
        ("observed", {"frozen_inputs_artifact": inputs}),
        ("flagged", {"triage": {"evidence": {"fixture": True}}}),
        ("diagnosed", {"output": {"issue_type": "procedure_defect", "trace_references": ["unit-source"], "evidence_pointers": ["/trace/tool_events/1/result"]}, "evidence": {"fixture": True}}),
    ):
        await tools.call("record_trace", {"event_type": "improvement_" + name,
            "payload": {"attempt_id": attempt, **payload}, "idempotency_key": f"improvement:{attempt}:{name}"})
    snapshot, provenance = await captured_training_snapshot(trace, tools)
    training = await tools.call("put_artifact", {"name": "training.json", "content": json.dumps({
        "contract": "finney-harness2-training-v1", "snapshot": snapshot, "provenance": provenance,
        "immutable_runtime_context": fixed, "immutable_policy": policy, "baseline_sha256": baseline["content_sha256"]})})
    candidate = replace_procedure(baseline_content, PROCEDURE)
    result = {"harness2_revision": HARNESS2_REVISION, "executor": "opencode", "budget": {"limit": 94, "used_upper_bound": 28},
              "results": [{"candidate": candidate}], "method": "upstream-propose-probe-compose-reflect"}
    # Deliberately scripted archive fixture; only continuation/gates are tested.
    calls = [{"kind": kind, "stage": str(i)} for i in range(4) for kind in ("probe", "editor")]
    archive = await persist_search_artifacts(tmp_path, tools, training, result, calls)
    connection.execute("update jobs set status='failed',error_code='runtime_dependency_or_persistence_failure',updated_at=now() where id=%s", (attempt,))
    monkeypatch.setattr("app.improvement.continuation.verify_binary", lambda _binary: None)
    return connection, tools, actor, attempt, archive, baseline


@pytest.mark.asyncio
async def test_continuation_uses_original_reservation_native_gates_and_one_shot_claim(state, tmp_path, monkeypatch):
    conn, tools, actor, attempt, archive, baseline = await prepared(state, tmp_path, monkeypatch)
    before = conn.execute("select reserved_model_calls,reserved_improvement_attempts from finance_run_execution_limits where run_id=%s", (tools.scope.run_id,)).fetchone()
    result = await continue_archived_search(connection=conn, tools=tools, actor=actor, attempt_id=attempt, archive_receipt=archive)
    assert result["status"] == "promoted"  # Explicit oracle fixture, never live evidence.
    assert len(actor.calls) == 8 and actor.calls[-4:] == [("transfer", False), ("transfer", True)] * 2
    assert result["model_call_budget"] == {"limit": 96, "used_upper_bound": 38}
    assert conn.execute("select reserved_model_calls,reserved_improvement_attempts from finance_run_execution_limits where run_id=%s", (tools.scope.run_id,)).fetchone() == before
    assert before == (96, 1)
    assert conn.execute("select status from jobs where id=%s", (attempt,)).fetchone()[0] == "failed"
    assert conn.execute("select count(*) from finance_improvement_holdouts where attempt_id=%s", (attempt,)).fetchone()[0] == 2
    assert (await tools.call("get_active_skill", {"skill_name": "organizer-expenses"}))["id"] != baseline["id"]
    with pytest.raises(ModelError, match="unfinished_original_attempt_required"):
        await continue_archived_search(connection=conn, tools=tools, actor=actor, attempt_id=attempt, archive_receipt=archive)
    assert len(actor.calls) == 8


@pytest.mark.asyncio
async def test_bad_transfer_still_rejects_and_never_activates(state, tmp_path, monkeypatch):
    conn, tools, actor, attempt, archive, baseline = await prepared(state, tmp_path, monkeypatch)
    actor.reject_transfer = True
    result = await continue_archived_search(connection=conn, tools=tools, actor=actor, attempt_id=attempt, archive_receipt=archive)
    assert result["status"] == "rejected"
    assert (await tools.call("get_active_skill", {"skill_name": "organizer-expenses"}))["id"] == baseline["id"]
    assert conn.execute("select status from finance_improvement_attempts where id=%s", (attempt,)).fetchone()[0] == "rejected"


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["model", "archive_hash", "prior_claim", "finished", "job_running", "dataset_pin"])
async def test_preflight_mismatch_or_replay_makes_zero_calls(state, tmp_path, monkeypatch, mutation):
    conn, tools, actor, attempt, archive, _baseline = await prepared(state, tmp_path, monkeypatch)
    if mutation == "model": actor.config = ModelConfig("new-model", "https://fixture.invalid/v1", "fixture")
    elif mutation == "archive_hash": archive = {**archive, "content_sha256": "f" * 64}
    elif mutation == "prior_claim":
        await tools.call("record_trace", {"event_type": "improvement_continuation_started", "payload": {"nonce": str(uuid4())}, "idempotency_key": f"improvement:{attempt}:continue-post-search"})
    elif mutation == "finished": conn.execute("update finance_improvement_attempts set status='blocked' where id=%s", (attempt,))
    elif mutation == "dataset_pin": monkeypatch.setattr("app.improvement.continuation.PROMOTION_MANIFEST_SHA256", "e" * 64)
    else: conn.execute("update jobs set status='running' where id=%s", (attempt,))
    with pytest.raises(ModelError):
        await continue_archived_search(connection=conn, tools=tools, actor=actor, attempt_id=attempt, archive_receipt=archive)
    assert actor.calls == []
    assert conn.execute("select count(*) from eval_runs where run_id=%s", (tools.scope.run_id,)).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_concurrent_continuations_have_one_atomic_winner_before_actor_calls(state, tmp_path, monkeypatch):
    conn, tools, actor, attempt, archive, _baseline = await prepared(state, tmp_path, monkeypatch)
    original = tools.call
    arrived = 0
    barrier = asyncio.Event()
    async def rendezvous(name, args):
        nonlocal arrived
        if name == "record_trace" and args.get("event_type") == "improvement_continuation_started":
            arrived += 1
            if arrived == 2:
                barrier.set()
            await barrier.wait()
        return await original(name, args)
    tools.call = rendezvous
    results = await asyncio.gather(*[
        continue_archived_search(connection=conn, tools=tools, actor=actor, attempt_id=attempt, archive_receipt=archive)
        for _ in range(2)
    ], return_exceptions=True)
    assert sum(isinstance(result, dict) and result["status"] == "promoted" for result in results) == 1
    assert sum(isinstance(result, psycopg.errors.UniqueViolation) for result in results) == 1
    assert len(actor.calls) == 8
    assert conn.execute("select count(*) from eval_runs where run_id=%s", (tools.scope.run_id,)).fetchone()[0] == 1


@pytest.mark.asyncio
async def test_read_only_preflight_checks_every_proof_without_claim_or_inference(state, tmp_path, monkeypatch):
    conn, tools, actor, attempt, archive, _baseline = await prepared(state, tmp_path, monkeypatch)
    before = len(tools.calls)
    result = await continue_archived_search(connection=conn, tools=tools, actor=actor, attempt_id=attempt, archive_receipt=archive, validate_only=True)
    assert result["status"] == "validated_read_only"
    assert result["maximum_remaining_evaluation_calls"] == 64 and result["used_upper_bound"] == 30
    assert result["continuation_claimed"] is False and actor.calls == []
    assert all(name in {"get_active_skill", "read_artifact"} for name, _ in tools.calls[before:])
    assert conn.execute("select count(*) from trace_events where idempotency_key=%s", (f"improvement:{attempt}:continue-post-search",)).fetchone()[0] == 0

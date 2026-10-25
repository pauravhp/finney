"""Actual engine/kernel lifecycle in isolated PostgreSQL; provider/storage fixtures.

No inference, network provider, hosted Storage, mailbox or payment operation is
performed. The shared database fixture creates and drops a random test database.
"""

from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb
from test_finance_postgres import (
    database as database,  # noqa: PLC0414 -- pytest fixture registration
)
from test_finance_postgres import (
    state as state,  # noqa: PLC0414 -- pytest fixture registration
)
from test_improvement_lifecycle import LifecycleActor, LifecycleJev, LifecycleReviewer

from app.finance.tools import FinanceToolClient
from app.finance.types import Scope
from app.improvement.blockers import BLOCKER_SUITE_ID
from app.improvement.engine import ImprovementEngine
from app.improvement.suites import organizer_expense_suite
from app.runtime.jobs import DEFAULT_SKILL, ensure_baseline


class LocalPostgresWithFixtureArtifacts:
    def __init__(self, connection):
        self.connection, self.artifacts = connection, {}

    async def rpc(self, name, arguments):
        assert name == "finance_kernel_call"
        return self.connection.execute(
            "select finance_kernel_call(%s,%s,%s,%s)",
            (
                arguments["p_organization_id"],
                arguments["p_run_id"],
                arguments["p_operation"],
                Jsonb(arguments["p_arguments"]),
            ),
        ).fetchone()[0]

    async def upload(self, bucket, path, content, content_type):
        assert bucket == "finance-artifacts"
        self.artifacts[path] = content

    async def download(self, bucket, path):
        assert bucket == "finance-artifacts"
        return self.artifacts[path]


@pytest.mark.asyncio
async def test_actual_engine_claim_evaluation_sql_promotion_and_rollback(state):
    connection, organization, run, _users = state
    backend = LocalPostgresWithFixtureArtifacts(connection)
    tools = FinanceToolClient(Scope(organization, run), backend)
    baseline = await ensure_baseline(tools)
    suite = organizer_expense_suite(tools, BLOCKER_SUITE_ID)
    actor, reviewer = LifecycleActor(suite), LifecycleReviewer(backend)
    trace = {
        "skill_version": baseline["id"],
        "output": {"explanation": "Explicit local fixture: redundant document reads."},
        "tool_events": [],
    }
    captured = await tools.call(
        "record_trace",
        {
            "event_type": "actor_completed",
            "payload": trace,
            "idempotency_key": "local-fixture-actor-completed",
        },
    )
    result = await ImprovementEngine(actor, reviewer, LifecycleJev()).run(
        trace={"id": captured["id"], **trace},
        baseline=baseline,
        baseline_content=DEFAULT_SKILL.read_text(),
        suite=suite,
        tools=tools,
    )
    assert result["status"] == "promoted"
    assert result["metrics"]["case_count"] == 4
    assert result["metrics"]["by_group"]["transfer"]["candidate_correct"] == 1
    assert (await tools.call("get_active_skill", {"skill_name": "organizer-expenses"}))[
        "id"
    ] == result["candidate"]["id"]
    rollback = await ImprovementEngine.rollback(
        tools,
        result["promotion"],
        reason="Declared local fixture monitoring failure",
        evidence_ids=[captured["id"]],
    )
    assert rollback["state"] == "rolled_back"
    assert (await tools.call("get_active_skill", {"skill_name": "organizer-expenses"}))[
        "id"
    ] == baseline["id"]
    second_actor, second_reviewer = LifecycleActor(suite), LifecycleReviewer(backend)
    repeated = await ImprovementEngine(second_actor, second_reviewer, LifecycleJev()).run(
        trace={"id": captured["id"], **trace},
        baseline=baseline,
        baseline_content=DEFAULT_SKILL.read_text(),
        suite=suite,
        tools=tools,
    )
    assert repeated["reason"] == "improvement_attempt_already_claimed"
    assert second_actor.events == [] and second_reviewer.prompts == []
    fresh_trace = await tools.call(
        "record_trace",
        {
            "event_type": "actor_completed",
            "payload": trace,
            "idempotency_key": "local-fixture-new-trace-" + str(uuid4()),
        },
    )
    consumed = await ImprovementEngine(second_actor, second_reviewer, LifecycleJev()).run(
        trace={"id": fresh_trace["id"], **trace},
        baseline=baseline,
        baseline_content=DEFAULT_SKILL.read_text(),
        suite=suite,
        tools=tools,
    )
    assert consumed["status"] == "blocked"
    assert consumed["reason"] == "transfer_holdout_already_consumed"
    assert len(second_actor.events) == 6
    connection.execute("reset role")
    assert connection.execute(
        "select reserved_model_calls,reserved_improvement_attempts from finance_run_execution_limits where run_id=%s",
        (run,),
    ).fetchone() == (80, 2)
    assert connection.execute(
        "select status,model_calls_used from finance_improvement_attempts where run_id=%s order by created_at",
        (run,),
    ).fetchall() == [("promoted", 11), ("blocked", 9)]

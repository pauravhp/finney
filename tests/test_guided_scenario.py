"""Actual PostgreSQL state/security checks; synthetic Storage, no model/provider calls."""

from uuid import UUID

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_demo import DemoPostgresWithFixtureStorage
from test_finance_postgres import database as database  # noqa: PLC0414
from test_finance_postgres import identity
from test_finance_postgres import state as state  # noqa: PLC0414

from app.config import Settings
from app.finance.tools import FinanceToolClient
from app.finance.types import Scope
from app.guided_demo import LEGACY_GUIDED_SCENARIO_VERSION as GUIDED_SCENARIO_VERSION
from app.guided_demo import seed_guided_scenario


class GuidedDB(DemoPostgresWithFixtureStorage):
    async def select(self, table, *, filters, limit=100):
        if table == "source_items" and "id" in filters:
            return [
                row[0]
                for row in self.connection.execute(
                    "select to_jsonb(s) from source_items s where organization_id=%s and run_id=%s and id=%s limit %s",
                    (
                        filters["organization_id"][3:],
                        filters["run_id"][3:],
                        filters["id"][3:],
                        limit,
                    ),
                ).fetchall()
            ]
        return await super().select(table, filters=filters, limit=limit)

    async def rpc(self, name, arguments):
        if name in {
            "assert_finance_guided_owner",
            "initialize_finance_guided_scenario",
            "finish_finance_guided_scenario",
        }:
            return self.connection.execute(
                f"select {name}(%s,%s,%s)",
                (arguments["p_organization_id"], arguments["p_run_id"], arguments["p_actor_id"]),
            ).fetchone()[0]
        return await super().rpc(name, arguments)


def create(state, owner=None):
    conn, org, _old_run, users = state
    owner = owner or users[0]
    conn.execute("reset role")
    # Disposable-DB compatibility checks for the retired, private legacy entrypoint.
    conn.execute("grant execute on function create_finance_guided_demo_v26() to authenticated")
    conn.execute(
        "update memberships set role='director' where organization_id=%s and user_id=%s",
        (org, owner),
    )
    identity(conn, owner)
    result = conn.execute("select create_finance_guided_demo_v26()").fetchone()[0]
    identity(conn, service=True)
    db = GuidedDB(conn)
    tools = FinanceToolClient(
        Scope(UUID(result["organization_id"]), UUID(result["run_id"]), owner), db
    )
    job = {
        "id": result["seed_job_id"],
        "organization_id": result["organization_id"],
        "run_id": result["run_id"],
        "requested_by": str(owner),
        "command_type": "intake",
        "payload": {"source": "demo_bundle", "bundle_version": GUIDED_SCENARIO_VERSION},
    }
    return conn, db, tools, job, result


@pytest.mark.asyncio
async def test_real_initial_state_amendment_resume_and_no_fabricated_outcomes(state):
    conn, db, tools, job, scope = create(state)
    result = await seed_guided_scenario(Settings(_env_file=None), tools, db, job)
    snap = await tools.call("get_financial_position", {})
    assert snap["cash_minor"] == "780000"
    assert snap["committed_minor"] == "368000"
    assert snap["available_minor"] == "412000"
    assert snap["receivable_minor"] == "250000"
    assert snap["evidence_status"] == "synthetic_scenario"
    full = conn.execute(
        "select get_finance_snapshot(%s,%s)", (scope["organization_id"], scope["run_id"])
    ).fetchone()[0]
    assert full["run"]["scenario"]["status"] == "ready"
    assert len(full["run"]["scenario"]["steps"]) == 3
    for step in full["run"]["scenario"]["steps"]:
        case = next(c for c in full["cases"] if c["id"] == step["case_id"])
        document = await tools.call("read_document", {"source_id": case["data"]["source_ids"][0]})
        assert "SYNTHETIC" in document["content"]
        assert ("420.00" if step["id"] != "report" else "87.00") in document["content"]
    last_step = full["run"]["scenario"]["steps"][2]
    assert (
        next(c for c in full["cases"] if c["id"] == last_step["case_id"])["title"]
        == "Mira · food reimbursement"
    )
    identity(conn, state[3][0])
    queued = conn.execute(
        "select enqueue_finance_command(%s,%s,'director_message',%s,'guided-step-report-context')",
        (
            scope["organization_id"],
            scope["run_id"],
            Jsonb({"case_id": last_step["case_id"], "message": last_step["prompt"]}),
        ),
    ).fetchone()[0]
    assert queued
    identity(conn, service=True)
    assert sum(int(x["allocated_minor"]) for x in full["budget"]["lines"]) == 780000
    assert result["source_results"] == []  # No pretend reviews and no eager paid calls.
    conn.execute("reset role")
    av = conn.execute(
        "select amount_minor,source_refs from obligations where run_id=%s and title like 'Harbor AV%%'",
        (scope["run_id"],),
    ).fetchone()
    assert av[0] == 48000 and av[1][0]["version"] == 1
    assert (
        conn.execute(
            "select count(*) from source_items where run_id=%s and external_id like '%%:av'",
            (scope["run_id"],),
        ).fetchone()[0]
        == 2
    )
    for table in [
        "approvals",
        "action_proposals",
        "payments",
        "budget_decisions",
        "promotions",
        "eval_runs",
        "skill_versions",
    ]:
        assert (
            conn.execute(
                f"select count(*) from {table} where run_id=%s", (scope["run_id"],)
            ).fetchone()[0]
            == 0
        )
    conn.execute(
        "update obligations set amount_minor=42000,version=version+1 where run_id=%s and title like 'Harbor AV%%'",
        (scope["run_id"],),
    )
    identity(conn, service=True)
    again = await seed_guided_scenario(Settings(_env_file=None), tools, db, job)
    assert again["source_results"] == []
    assert (await tools.call("get_financial_position", {}))["committed_minor"] == "362000"
    identity(conn, state[3][0])
    resumed = conn.execute("select create_finance_guided_demo_v26()").fetchone()[0]
    assert resumed["run_id"] == scope["run_id"] and resumed["seed_job_id"] == scope["seed_job_id"]


@pytest.mark.asyncio
async def test_owner_isolation_and_non_guided_runs_rejected(state):
    conn, db, tools, job, scope = create(state)
    wrong = {**job, "requested_by": str(state[3][1])}
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        await seed_guided_scenario(Settings(_env_file=None), tools, db, wrong)
    assert db.artifacts == {}
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(
            "select initialize_finance_guided_scenario(%s,%s,%s)", (state[1], state[2], state[3][0])
        )
    identity(conn, state[3][1])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(
            "select get_finance_snapshot(%s,%s)", (scope["organization_id"], scope["run_id"])
        )
    # A second director receives a different run, even in the same organization.
    conn, db2, tools2, job2, scope2 = create(state, state[3][1])
    assert scope2["run_id"] != scope["run_id"]
    await seed_guided_scenario(Settings(_env_file=None), tools2, db2, job2)
    conn.execute("reset role")
    assert (
        conn.execute(
            "select count(*) from obligations where run_id=%s", (scope["run_id"],)
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute("select count(*) from obligations where run_id=%s", (state[2],)).fetchone()[0]
        == 0
    )


@pytest.mark.asyncio
async def test_initialization_fails_closed_with_existing_financial_state(state):
    conn, db, tools, job, scope = create(state)
    conn.execute("reset role")
    conn.execute(
        "insert into budget_lines(organization_id,run_id,name,currency,allocated_minor) values(%s,%s,'Existing owner work','USD',19)",
        (scope["organization_id"], scope["run_id"]),
    )
    identity(conn, service=True)
    with pytest.raises(psycopg.errors.CheckViolation):
        await seed_guided_scenario(Settings(_env_file=None), tools, db, job)
    conn.execute("reset role")
    assert (
        conn.execute(
            "select count(*) from ledger_transactions where run_id=%s", (scope["run_id"],)
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "select allocated_minor from budget_lines where run_id=%s", (scope["run_id"],)
        ).fetchone()[0]
        == 19
    )


@pytest.mark.asyncio
async def test_real_version_guard_denial_recovery_and_report(state):
    from test_finance_postgres import call

    from app.finance.workflows import build_close_report

    conn, db, tools, job, _scope = create(state)
    await seed_guided_scenario(Settings(_env_file=None), tools, db, job)
    org, run = tools.scope.organization_id, tools.scope.run_id
    snapshot = conn.execute("select get_finance_snapshot(%s,%s)", (org, run)).fetchone()[0]
    conn.execute("reset role")
    av = conn.execute(
        "select to_jsonb(o) from obligations o where run_id=%s and title like 'Harbor AV%%'", (run,)
    ).fetchone()[0]
    current = conn.execute(
        "select id from source_items where run_id=%s and external_id like '%%:av' and version=2",
        (run,),
    ).fetchone()[0]
    identity(conn, service=True)
    args = {
        "id": av["id"],
        "expected_version": 1,
        "title": av["title"],
        "amount_minor": "42000",
        "currency": "USD",
        "direction": "payable",
        "source_refs": av["source_refs"],
        "idempotency_key": "actual-test-source-guard",
    }
    with pytest.raises(
        psycopg.errors.CheckViolation, match="source reference missing, stale or outside run"
    ):
        call(conn, org, run, "propose_obligation_update", args)
    args["source_refs"] = [{"id": str(current), "version": 2}]
    call(conn, org, run, "propose_obligation_update", args)
    avline = next(x for x in snapshot["budget"]["lines"] if x["name"] == "AV")
    decision_args = {
        "budget_line_id": avline["id"],
        "expected_version": 1,
        "allocated_minor": "100000",
        "rationale": "Proposed additional equipment headroom",
        "idempotency_key": "guided-actual-budget-decision",
    }
    proposal = conn.execute(
        "select propose_finance_budget(%s,%s,%s)", (org, run, Jsonb(decision_args))
    ).fetchone()[0]
    # The seed has no authority to approve. Only this explicit authenticated test
    # director action creates the rejection, through the real existing gate.
    identity(conn, state[3][0])
    decision = conn.execute(
        "select decide_finance_budget(%s,%s,%s,'reject')", (org, run, proposal["id"])
    ).fetchone()[0]
    assert decision["status"] == "rejected"
    final = conn.execute("select get_finance_snapshot(%s,%s)", (org, run)).fetchone()[0]
    assert (
        next(x for x in final["budget"]["lines"] if x["name"] == "AV")["allocated_minor"] == "80000"
    )
    assert (
        final["position"]["cash_minor"] == "780000"
        and final["position"]["available_minor"] == "418000"
    )
    conn.execute("reset role")
    obligations = [
        x[0]
        for x in conn.execute(
            "select to_jsonb(o) from obligations o where run_id=%s", (run,)
        ).fetchall()
    ]
    report = build_close_report(final, obligations, cutoff="2026-10-25")
    assert report["totals_by_currency"]["USD"] == {
        "payable_minor": "362000",
        "paid_minor": "0",
        "receivable_minor": "250000",
        "received_minor": "0",
    }
    assert report["reconciliation"]["status"] == "not_reconciled"
    identity(conn, service=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        call(conn, org, run, "assert_payment_run_authorized", {})


def test_guided_creation_denies_anonymous_and_service_bypass(state):
    conn, _org, _run, users = state
    identity(conn, service=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select create_finance_guided_demo_v26()")
    identity(conn, users[0])
    conn.execute("select set_config('request.jwt.claims','{\"is_anonymous\":true}',false)")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select create_finance_guided_demo_v26()")
    conn.execute("select set_config('request.jwt.claims','{}',false)")


@pytest.mark.asyncio
async def test_failed_seed_explicit_retry_preserves_failure_and_reaches_ready(state):
    conn, db, tools, job, scope = create(state)
    original_job = scope["seed_job_id"]
    conn.execute("reset role")
    conn.execute(
        "update jobs set status='failed',error_code='demo_bundle_payload_invalid' where id=%s",
        (original_job,),
    )
    identity(conn, state[3][0])
    before = conn.execute(
        "select get_finance_snapshot(%s,%s)", (scope["organization_id"], scope["run_id"])
    ).fetchone()[0]
    assert before["run"]["scenario"]["seed_status"] == "failed"
    assert before["run"]["scenario"]["seed_retry_available"] is True
    retried = conn.execute("select create_finance_guided_demo_v26()").fetchone()[0]
    assert retried["run_id"] == scope["run_id"]
    assert retried["seed_job_id"] != original_job
    assert retried["seed_attempts"] == 2 and retried["seed_status"] == "queued"
    assert retried["seed_retry_available"] is False
    again = conn.execute("select create_finance_guided_demo_v26()").fetchone()[0]
    assert again["seed_job_id"] == retried["seed_job_id"]
    identity(conn, service=True)
    await seed_guided_scenario(
        Settings(_env_file=None), tools, db, {**job, "id": retried["seed_job_id"]}
    )
    identity(conn, state[3][0])
    ready = conn.execute("select create_finance_guided_demo_v26()").fetchone()[0]
    assert ready["seed_status"] == "ready" and ready["seed_attempts"] == 2
    assert ready["seed_retry_available"] is False
    conn.execute("reset role")
    assert conn.execute(
        "select status,error_code from jobs where id=%s", (original_job,)
    ).fetchone() == ("failed", "demo_bundle_payload_invalid")
    assert (
        conn.execute(
            "select count(*) from ledger_transactions where run_id=%s", (scope["run_id"],)
        ).fetchone()[0]
        == 1
    )


def test_seed_recovery_bound_and_concurrent_resumes(state, database):
    from concurrent.futures import ThreadPoolExecutor

    conn, _db, _tools, _job, scope = create(state)
    original_job = scope["seed_job_id"]
    conn.execute("reset role")
    conn.execute(
        "update jobs set status='failed',error_code='prior_worker_rejected_bundle' where id=%s",
        (original_job,),
    )

    def resume():
        with psycopg.connect(database, autocommit=True) as separate:
            identity(separate, state[3][0])
            return separate.execute("select create_finance_guided_demo_v26()").fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: resume(), range(2)))
    assert results[0]["seed_job_id"] == results[1]["seed_job_id"]
    assert all(r["seed_attempts"] == 2 and r["seed_status"] == "queued" for r in results)
    second = results[0]["seed_job_id"]
    conn.execute(
        "update jobs set status='blocked',error_code='fixture_setup_failure' where id=%s", (second,)
    )
    third = resume()
    assert third["seed_attempts"] == 3 and third["seed_job_id"] != second
    conn.execute(
        "update jobs set status='failed',error_code='fixture_setup_failure' where id=%s",
        (third["seed_job_id"],),
    )
    for _ in range(2):
        capped = resume()
        assert capped["seed_attempts"] == 3 and capped["seed_status"] == "failed"
        assert capped["seed_retry_available"] is False
        assert capped["seed_job_id"] == third["seed_job_id"]
    assert (
        conn.execute("select count(*) from jobs where run_id=%s", (scope["run_id"],)).fetchone()[0]
        == 3
    )
    assert (
        conn.execute(
            "select count(*) from audit_events where run_id=%s and event_type='guided_seed_retry_requested'",
            (scope["run_id"],),
        ).fetchone()[0]
        == 2
    )
    assert (
        conn.execute(
            "select count(*) from source_items where run_id=%s", (scope["run_id"],)
        ).fetchone()[0]
        == 0
    )

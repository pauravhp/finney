"""Seed/limit integration uses actual isolated SQL and explicit private-Storage fixtures.

There are no provider or model calls. All financial/source documents are synthetic.
"""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from test_finance_postgres import call, identity, opening
from test_finance_postgres import (
    database as database,  # noqa: PLC0414 -- pytest fixture registration
)
from test_finance_postgres import (
    state as state,  # noqa: PLC0414 -- pytest fixture registration
)
from test_finance_runtime_guards import attempt_arguments, skill_pair
from test_improvement_postgres import LocalPostgresWithFixtureArtifacts

from app.config import Settings
from app.demo import DEMO_BUNDLE_VERSION, demo_source_bundle, seed_demo_bundle
from app.finance.tools import FinanceToolClient
from app.finance.types import FinanceError, Scope


class DemoPostgresWithFixtureStorage(LocalPostgresWithFixtureArtifacts):
    async def rpc(self, name, arguments):
        if name == "get_finance_snapshot":
            return self.connection.execute(
                "select get_finance_snapshot(%s,%s)",
                (arguments["p_organization_id"], arguments["p_run_id"]),
            ).fetchone()[0]
        if name == "assert_finance_demo_owner":
            return self.connection.execute(
                "select assert_finance_demo_owner(%s,%s,%s)",
                (arguments["p_organization_id"], arguments["p_run_id"], arguments["p_actor_id"]),
            ).fetchone()[0]
        return await super().rpc(name, arguments)

    async def select(self, table, *, filters, limit=100):
        assert table in {"cases", "source_items"}
        clauses, values = [], []
        order = sql.SQL("")
        for field, value in filters.items():
            if field == "order":
                assert value == "version.desc"
                order = sql.SQL(" order by version desc")
                continue
            assert value.startswith("eq.")
            if field == "data->>source_external_id":
                clauses.append(sql.SQL("data->>'source_external_id'=%s"))
            else:
                assert field in {"organization_id", "run_id", "external_id"}
                clauses.append(sql.SQL("{}=%s").format(sql.Identifier(field)))
            values.append(value[3:])
        query = sql.SQL("select to_jsonb(t) from {} t where {}{} limit %s").format(
            sql.Identifier(table), sql.SQL(" and ").join(clauses), order
        )
        return [row[0] for row in self.connection.execute(query, (*values, limit)).fetchall()]


def demo_state(state):
    conn, org, run, users = state
    conn.execute("reset role")
    conn.execute(
        "update memberships set role='director' where user_id=%s and organization_id=%s",
        (users[0], org),
    )
    conn.execute("update demo_runs set is_demo=true,owner_user_id=%s where id=%s", (users[0], run))
    identity(conn, service=True)
    return conn, org, run, users


def seed_arguments(state):
    conn, org, run, users = demo_state(state)
    db = DemoPostgresWithFixtureStorage(conn)
    tools = FinanceToolClient(Scope(org, run, users[0]), db)
    job = {
        "id": str(uuid4()),
        "organization_id": str(org),
        "run_id": str(run),
        "requested_by": str(users[0]),
        "command_type": "intake",
        "payload": {"source": "demo_bundle"},
    }
    return conn, tools, db, job


def test_corpus_is_detached_labeled_factual_input_without_answers():
    documents = demo_source_bundle()
    assert len(documents) == 2
    for evidence in documents:
        assert evidence["synthetic"] is True
        assert "expected" not in evidence and "decision" not in evidence
        assert all("SYNTHETIC DOCUMENT" in item["text"] for item in evidence["documents"])
    documents[0]["documents"][0]["text"] = "caller mutation"
    assert "SYNTHETIC DOCUMENT" in demo_source_bundle()[0]["documents"][0]["text"]


@pytest.mark.asyncio
async def test_seed_persists_real_sources_cases_and_preserves_human_edits_on_retry(state):
    conn, tools, db, job = seed_arguments(state)
    result = await seed_demo_bundle(Settings(_env_file=None), tools, db, job)
    assert result["status"] == "completed" and result["bundle_version"] == DEMO_BUNDLE_VERSION
    assert result["cash_established_by_seed"] is False and result["payments_enabled"] is False
    assert len(result["source_results"]) == 2
    assert all(item["review_required"] for item in result["source_results"])
    first_case = result["source_results"][0]["case_id"]
    original = await tools.call("get_case", {"case_id": first_case})
    # Explicit fixture of a later human change; seeding must never reset it.
    await tools.call(
        "record_case",
        {
            "id": first_case,
            "expected_version": original["version"],
            "title": "Director's edited case",
            "status": "closed",
            "data": {**original["data"], "finding": "Human-reviewed fixture"},
            "idempotency_key": "human-case-edit-fixture",
        },
    )
    edited = await tools.call("get_case", {"case_id": first_case})
    job["id"] = str(uuid4())
    again = await seed_demo_bundle(Settings(_env_file=None), tools, db, job)
    assert again["source_results"][0]["status"] == "preserved"
    assert again["source_results"][0]["review_required"] is False
    assert again["source_results"][1]["review_required"] is True  # Crash-before-queue recovery.
    assert (await tools.call("get_case", {"case_id": first_case})) == edited
    assert [item["source_id"] for item in result["source_results"]] == [
        item["source_id"] for item in again["source_results"]
    ]
    conn.execute("reset role")
    assert (
        conn.execute(
            "select count(*) from source_items where run_id=%s", (tools.scope.run_id,)
        ).fetchone()[0]
        == 2
    )
    assert (
        conn.execute(
            "select count(*) from cases where run_id=%s", (tools.scope.run_id,)
        ).fetchone()[0]
        == 2
    )
    assert (
        conn.execute(
            "select count(*) from trace_events where run_id=%s and event_type='demo_bundle_seeded'",
            (tools.scope.run_id,),
        ).fetchone()[0]
        == 1
    )
    for table in (
        "obligations",
        "payments",
        "approvals",
        "ledger_transactions",
        "skill_versions",
        "promotions",
        "jobs",
    ):
        assert (
            conn.execute(
                sql.SQL("select count(*) from {} where run_id=%s").format(sql.Identifier(table)),
                (tools.scope.run_id,),
            ).fetchone()[0]
            == 0
        )
    assert (
        conn.execute(
            "select cash_established from demo_runs where id=%s", (tools.scope.run_id,)
        ).fetchone()[0]
        is False
    )


@pytest.mark.asyncio
async def test_seed_rejects_scope_owner_policy_payload_and_non_demo_before_storage(state):
    conn, tools, db, job = seed_arguments(state)
    for change in (
        {"run_id": str(uuid4())},
        {"requested_by": str(uuid4())},
        {"payload": {"source": "demo_bundle", "cash_minor": "1000"}},
        {"payload": {"source": "demo_bundle", "bundle_version": "invented"}},
    ):
        with pytest.raises((FinanceError, psycopg.errors.InsufficientPrivilege)):
            await seed_demo_bundle(Settings(_env_file=None), tools, db, {**job, **change})
        assert db.artifacts == {}
    conn.execute("reset role")
    conn.execute("update demo_runs set is_demo=false where id=%s", (tools.scope.run_id,))
    identity(conn, service=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        await seed_demo_bundle(Settings(_env_file=None), tools, db, job)
    assert db.artifacts == {}


@pytest.mark.asyncio
async def test_seed_never_replaces_existing_cash_or_ledger(state):
    conn, tools, db, job = seed_arguments(state)
    opening(conn, tools.scope.organization_id, tools.scope.run_id, amount=300)
    before = await tools.call("get_financial_position", {})
    result = await seed_demo_bundle(Settings(_env_file=None), tools, db, job)
    assert result["cash_established_by_seed"] is False
    assert (await tools.call("get_financial_position", {})) == before
    assert before["cash_minor"] == "300"


@pytest.mark.parametrize("change", ["active=false", "role='finance'"])
def test_seed_authority_requires_current_director(state, change):
    conn, org, run, users = demo_state(state)
    conn.execute("reset role")
    conn.execute(
        "update memberships set " + change + " where user_id=%s and organization_id=%s",
        (users[0], org),
    )
    identity(conn, service=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select assert_finance_demo_owner(%s,%s,%s)", (org, run, users[0]))


@pytest.mark.parametrize("change", ["status='cancelled'", "expires_at=now()-interval '1 hour'"])
def test_seed_authority_rejects_cancelled_or_expired_demo(state, change):
    conn, org, run, users = demo_state(state)
    conn.execute("reset role")
    conn.execute("update demo_runs set " + change + " where id=%s", (run,))
    identity(conn, service=True)
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        conn.execute("select assert_finance_demo_owner(%s,%s,%s)", (org, run, users[0]))


def reserve(conn, org, run, calls=40, reservation=None):
    return call(
        conn,
        org,
        run,
        "reserve_run_inference",
        {"reservation_id": str(reservation or uuid4()), "max_model_calls": calls},
    )


def test_demo_budget_survives_reset_and_duplicate_cannot_renew_or_double_charge(state):
    conn, org, run, users = demo_state(state)
    conn.execute("reset role")
    before = conn.execute(
        "select coalesce(sum(reserved_model_calls),0) from finance_demo_daily_limits"
    ).fetchone()[0]
    identity(conn, service=True)
    reservation = uuid4()
    assert reserve(conn, org, run, reservation=reservation)["claimed"]
    assert not reserve(conn, org, run, reservation=reservation)["claimed"]
    assert reserve(conn, org, run)["claimed"] and reserve(conn, org, run)["claimed"]
    identity(conn, users[0])
    reset = conn.execute(
        "select create_finance_demo('Reset retains allowance',%s)", (run,)
    ).fetchone()[0]
    identity(conn, service=True)
    assert (
        reserve(conn, reset["organization_id"], reset["run_id"], 1)["reason"]
        == "demo_owner_lifetime_model_budget_exhausted"
    )
    conn.execute("reset role")
    assert (
        conn.execute(
            "select reserved_model_calls from finance_demo_owner_limits where user_id=%s",
            (users[0],),
        ).fetchone()[0]
        == 120
    )
    assert (
        conn.execute("select reserved_model_calls from finance_demo_daily_limits").fetchone()[0]
        == before + 120
    )


def test_improvement_reservation_uses_same_owner_allowance_and_inner_failure_is_free(state):
    conn, org, run, users = demo_state(state)
    conn.execute("reset role")
    before = conn.execute(
        "select coalesce(sum(reserved_model_calls),0) from finance_demo_daily_limits"
    ).fetchone()[0]
    identity(conn, service=True)
    baseline, _candidate = skill_pair(conn, org, run)
    attempt = attempt_arguments(conn, org, run, baseline)
    assert call(conn, org, run, "claim_improvement_attempt", attempt)["claimed"]
    assert not call(
        conn, org, run, "claim_improvement_attempt", {**attempt, "attempt_id": str(uuid4())}
    )["claimed"]
    assert (
        call(
            conn,
            org,
            run,
            "finish_improvement_attempt",
            {
                "attempt_id": attempt["attempt_id"],
                "status": "blocked",
                "model_calls_used": 1,
                "reason": "Fixture provider unavailable",
            },
        )["status"]
        == "blocked"
    )
    conn.execute("reset role")
    conn.execute(
        "update finance_run_execution_limits set model_call_limit=40 where run_id=%s", (run,)
    )
    identity(conn, service=True)
    assert reserve(conn, org, run, 1)["reason"] == "run_model_call_budget_exhausted"
    conn.execute("reset role")
    assert (
        conn.execute(
            "select reserved_model_calls from finance_demo_owner_limits where user_id=%s",
            (users[0],),
        ).fetchone()[0]
        == 40
    )
    assert (
        conn.execute("select reserved_model_calls from finance_demo_daily_limits").fetchone()[0]
        == before + 40
    )


def test_global_public_demo_budget_is_atomic_across_distinct_owners(database, state):
    conn, _org, _run, users = state
    scopes = []
    for user in users[:3]:
        identity(conn, user)
        scopes.append(
            conn.execute("select create_finance_demo('Global cap fixture',null)").fetchone()[0]
        )
    conn.execute("reset role")
    initial = conn.execute(
        "select coalesce(sum(reserved_model_calls),0) from finance_demo_daily_limits"
    ).fetchone()[0]
    owner_initial = conn.execute(
        "select coalesce(sum(reserved_model_calls),0) from finance_demo_owner_limits"
    ).fetchone()[0]
    conn.execute(
        "insert into finance_demo_daily_limits(utc_day,model_call_limit) values((now() at time zone 'UTC')::date,%s) on conflict(utc_day) do update set model_call_limit=excluded.model_call_limit",
        (initial + 80,),
    )

    def worker(scope):
        with psycopg.connect(database, autocommit=True) as current:
            identity(current, service=True)
            return reserve(current, scope["organization_id"], scope["run_id"])

    with ThreadPoolExecutor(3) as pool:
        outcomes = list(pool.map(worker, scopes))
    assert sum(item["claimed"] for item in outcomes) == 2
    assert [item["reason"] for item in outcomes if not item["claimed"]] == [
        "demo_daily_model_budget_exhausted"
    ]
    assert (
        conn.execute("select reserved_model_calls from finance_demo_daily_limits").fetchone()[0]
        == initial + 80
    )
    assert (
        conn.execute("select sum(reserved_model_calls) from finance_demo_owner_limits").fetchone()[
            0
        ]
        == owner_initial + 80
    )
    conn.execute("update finance_demo_daily_limits set model_call_limit=600")


def test_budget_tables_and_previous_kernel_cannot_be_mutated_or_called_directly(state):
    conn, org, run, users = demo_state(state)
    assert reserve(conn, org, run, 1)["claimed"]
    for actor in (users[0], users[1]):
        identity(conn, actor)
        rows = conn.execute("select user_id from finance_demo_owner_limits").fetchall()
        assert rows == [(users[0],)] if actor == users[0] else rows == []
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("update finance_demo_owner_limits set model_call_limit=1000")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("select assert_finance_demo_owner(%s,%s,%s)", (org, run, actor))
    identity(conn, service=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("update finance_demo_daily_limits set reserved_model_calls=0")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(
            "select finance_kernel_call_v12(%s,%s,'reserve_run_inference','{}')", (org, run)
        )

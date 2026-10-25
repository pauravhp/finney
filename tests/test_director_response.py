"""Actual isolated SQL and explicit local response/Storage fixtures; no inference."""

import copy
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_finance_postgres import (
    database as database,  # noqa: PLC0414 -- pytest fixture registration
)
from test_finance_postgres import identity
from test_finance_postgres import (
    state as state,  # noqa: PLC0414 -- pytest fixture registration
)
from test_improvement_postgres import LocalPostgresWithFixtureArtifacts

from app.finance.director_response import (
    DIRECTOR_OUTPUT_CONTRACT,
    consulted_source_refs,
    persist_director_response,
)
from app.finance.tools import FinanceToolClient
from app.finance.types import FinanceError, Scope
from app.runtime.hermes import ACTOR_TOOLS
from app.storage.supabase import SupabaseError

QUERY = "select record_finance_director_response(%s,%s,%s,%s,%s,%s,%s,%s,%s)"


class ConversationBackend(LocalPostgresWithFixtureArtifacts):
    async def rpc(self, name, args):
        try:
            if name == "record_finance_director_response":
                return self.connection.execute(
                    QUERY,
                    (
                        args["p_organization_id"],
                        args["p_run_id"],
                        args["p_case_id"],
                        args["p_expected_version"],
                        args["p_expected_source_ids"],
                        args["p_trace_id"],
                        args["p_job_id"],
                        Jsonb(args["p_response"]),
                        args["p_idempotency_key"],
                    ),
                ).fetchone()[0]
            if name == "get_finance_snapshot":
                return self.connection.execute(
                    "select get_finance_snapshot(%s,%s)",
                    (args["p_organization_id"], args["p_run_id"]),
                ).fetchone()[0]
            return await super().rpc(name, args)
        except psycopg.Error as error:
            # Explicit fixture of the real HTTP adapter's safe error projection.
            raise SupabaseError(400, error.sqlstate) from None

    async def select(self, table, *, filters, limit=100):
        assert table == "source_items"
        assert set(filters) == {"organization_id", "run_id", "id"}
        return [
            row[0]
            for row in self.connection.execute(
                "select to_jsonb(s) from source_items s where organization_id=%s and run_id=%s and id=%s limit %s",
                (filters["organization_id"][3:], filters["run_id"][3:], filters["id"][3:], limit),
            ).fetchall()
        ]


async def response_fixture(state, *, tools=None, before=None):
    conn, org, run, users = state
    if tools is None:
        tools = FinanceToolClient(Scope(org, run, users[0]), ConversationBackend(conn))
        artifact = await tools.call(
            "put_artifact",
            {
                "name": "synthetic-context.txt",
                "content": "SYNTHETIC statement coverage note. No opening bank statement is provided.",
            },
        )
        source = await tools.call(
            "record_source",
            {
                "external_id": "conversation-context",
                "version": 1,
                "source_type": "test_fixture",
                "content_sha256": artifact["content_sha256"],
                "artifact_path": artifact["artifact_path"],
                "idempotency_key": "conversation-source",
            },
        )
        case = await tools.call(
            "record_case",
            {
                "title": "Conversation fixture",
                "status": "awaiting_evidence",
                "data": {
                    "source_ids": [source["id"]],
                    "finding": {"kind": "prepared_agent_review", "decision": "investigate"},
                    "human_note": "Preserve me",
                },
                "idempotency_key": "conversation-case",
            },
        )
        before = await tools.call("get_case", {"case_id": case["id"]})
    document = await tools.call("read_document", {"source_id": before["data"]["source_ids"][0]})
    events = [
        {"name": "read_document", "arguments": {"source_id": document["id"]}, "result": document}
    ]
    refs = consulted_source_refs(events)
    output = {
        "response_type": "director_response",
        "message": "## Current cash\nIt is **unknown**. We need the opening statement. <em>Untrusted document text</em>",
        "evidence_source_ids": [ref["id"] for ref in refs],
        "consulted_source_refs": refs,
    }
    identity(conn, users[0])
    job_id = conn.execute(
        "select enqueue_finance_command(%s,%s,'director_message',%s,%s)",
        (
            org,
            run,
            Jsonb({"case_id": before["id"], "message": "What is the recorded cash position?"}),
            "conversation-job:" + str(uuid4()),
        ),
    ).fetchone()[0]
    identity(conn, service=True)
    conn.execute("update jobs set status='running' where id=%s", (job_id,))
    job = {
        "id": str(job_id),
        "organization_id": str(org),
        "run_id": str(run),
        "requested_by": str(users[0]),
        "command_type": "director_message",
        "payload": {"case_id": before["id"]},
    }
    payload = {
        "job_id": str(job_id),
        "skill_version": "bundle:explicit-local-conversation-fixture",
        "improvement_eligible": False,
        "output": output,
        "tool_events": events,
        "evidence": {"output_contract": DIRECTOR_OUTPUT_CONTRACT},
    }
    trace = await tools.call(
        "record_trace",
        {
            "event_type": "actor_completed",
            "payload": payload,
            "idempotency_key": "conversation-actor:" + str(job_id),
        },
    )
    outcome = {"status": "completed", "trace": trace, **copy.deepcopy(payload)}
    response = {
        "message": output["message"],
        "consulted_source_ids": output["evidence_source_ids"],
        "consulted_source_refs": refs,
        "provenance": {
            "source_case_version": before["version"],
            "source_ids": before["data"]["source_ids"],
        },
    }
    args = [
        org,
        run,
        before["id"],
        before["version"],
        before["data"]["source_ids"],
        trace["id"],
        str(job_id),
        Jsonb(response),
        "director-response:" + str(job_id),
    ]
    return SimpleNamespace(
        conn=conn,
        org=org,
        run=run,
        users=users,
        tools=tools,
        before=before,
        events=events,
        output=output,
        payload=payload,
        job=job,
        trace=trace,
        outcome=outcome,
        response=response,
        args=args,
    )


async def capture_new_fixture_trace(fx):
    """Keep old immutable records intact when testing a different emitted trace."""
    fx.trace = await fx.tools.call(
        "record_trace",
        {
            "event_type": "actor_completed",
            "payload": fx.payload,
            "idempotency_key": "different-emitted-trace:" + str(uuid4()),
        },
    )
    fx.outcome = {"status": "completed", "trace": fx.trace, **copy.deepcopy(fx.payload)}
    fx.args[5] = fx.trace["id"]


def test_consulted_refs_come_only_from_successful_actual_document_results():
    first, second = sorted([str(uuid4()), str(uuid4())])
    rows = [
        {"name": "read_document", "result": {"id": first, "version": 1}},
        {"name": "read_document", "result": {"id": str(uuid4()), "version": 2, "status": "failed"}},
        {"name": "get_case", "result": {"id": str(uuid4()), "version": 1}},
        {
            "name": "read_thread",
            "result": {"documents": [{"id": second, "version": 3}, {"id": first, "version": 1}]},
        },
        {
            "name": "read_thread",
            "result": {"documents": [{"id": str(uuid4()), "version": 1}], "error": "denied"},
        },
    ]
    assert consulted_source_refs(rows) == [
        {"id": first, "version": 1},
        {"id": second, "version": 3},
    ]
    with pytest.raises(FinanceError):
        consulted_source_refs([{"name": "read_document", "result": {"id": first, "version": True}}])
    with pytest.raises(FinanceError):
        consulted_source_refs(
            rows + [{"name": "read_document", "result": {"id": first, "version": 4}}]
        )
    assert "record_director_response" not in ACTOR_TOOLS


@pytest.mark.asyncio
async def test_actual_response_append_preserves_financial_finding_status_and_idempotency(state):
    fx = await response_fixture(state)
    first = await persist_director_response(fx.tools, fx.before, fx.outcome, fx.job)
    assert first["status"] == "persisted"
    current = await fx.tools.call("get_case", {"case_id": fx.before["id"]})
    assert current["status"] == fx.before["status"]
    assert current["data"]["finding"] == fx.before["data"]["finding"]
    assert current["data"]["human_note"] == "Preserve me"
    assert current["version"] == fx.before["version"] + 1
    entry = current["data"]["director_responses"][0]
    assert entry["message"] == fx.output["message"] and entry["source_label"] == "consulted"
    assert entry["job_id"] == fx.job["id"] and entry["trace_id"] == fx.trace["id"]
    assert entry["consulted_source_refs"] == fx.output["consulted_source_refs"]
    assert not {"decision", "proposed_action", "approved", "approval_count", "paid"} & set(entry)
    second = await persist_director_response(fx.tools, fx.before, fx.outcome, fx.job)
    assert first == second
    assert (await fx.tools.call("get_case", {"case_id": fx.before["id"]}))["version"] == current[
        "version"
    ]
    await fx.tools.call(
        "record_case",
        {
            "id": current["id"],
            "expected_version": current["version"],
            "title": current["title"],
            "status": "closed",
            "data": current["data"],
            "idempotency_key": "director-closed-fixture",
        },
    )
    current = await fx.tools.call("get_case", {"case_id": fx.before["id"]})
    next_fx = await response_fixture(state, tools=fx.tools, before=current)
    assert (
        await persist_director_response(next_fx.tools, next_fx.before, next_fx.outcome, next_fx.job)
    )["status"] == "persisted"
    current = await fx.tools.call("get_case", {"case_id": fx.before["id"]})
    assert len(current["data"]["director_responses"]) == 2
    assert current["data"]["finding"] == fx.before["data"]["finding"]
    assert current["status"] == "closed"
    fx.conn.execute("reset role")
    for table in ("payments", "approvals", "ledger_transactions", "obligations", "promotions"):
        assert (
            fx.conn.execute(f"select count(*) from {table} where run_id=%s", (fx.run,)).fetchone()[
                0
            ]
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["message", "events", "contract", "eligible", "case_version", "case_sources", "source_version"],
)
async def test_helper_blocks_mismatched_or_stale_response_context_without_rebasing(state, change):
    fx = await response_fixture(state)
    if change == "message":
        fx.outcome["output"]["message"] += " invented"
    elif change == "events":
        fx.outcome["tool_events"] = []
    elif change == "contract":
        fx.outcome["evidence"]["output_contract"] = "finance-decision-v2"
    elif change == "eligible":
        fx.payload["improvement_eligible"] = True
        await capture_new_fixture_trace(fx)
    elif change == "case_version":
        fx.conn.execute("update cases set version=version+1 where id=%s", (fx.before["id"],))
    elif change == "case_sources":
        fx.conn.execute(
            "update cases set data=jsonb_set(data,'{source_ids}','[]') where id=%s",
            (fx.before["id"],),
        )
    elif change == "source_version":
        fx.payload["tool_events"][0]["result"]["version"] = 2
        fx.payload["output"]["consulted_source_refs"][0]["version"] = 2
        await capture_new_fixture_trace(fx)
    result = await persist_director_response(fx.tools, fx.before, fx.outcome, fx.job)
    assert result["status"] == "blocked"
    current = await fx.tools.call("get_case", {"case_id": fx.before["id"]})
    assert "director_responses" not in current["data"]
    assert current["data"]["finding"] == fx.before["data"]["finding"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "message",
        "financial_field",
        "refs",
        "stale_case",
        "failed_read",
        "invented_read",
        "wrong_contract",
        "wrong_command",
        "revoked_editor",
        "read_version",
        "foreign_source",
        "demo_owner",
        "cancelled_job",
    ],
)
async def test_sql_independently_denies_tampered_response_authority_and_sources(state, change):
    fx = await response_fixture(state)
    response = copy.deepcopy(fx.response)
    if change == "message":
        response["message"] = "A different reply"
    elif change == "financial_field":
        response["approved"] = True
    elif change == "refs":
        response["consulted_source_refs"][0]["version"] += 1
    elif change == "stale_case":
        fx.args[3] += 1
    elif change == "failed_read":
        fx.payload["tool_events"][0]["result"]["status"] = "failed"
    elif change == "invented_read":
        fx.payload["tool_events"] = []
    elif change == "wrong_contract":
        fx.payload["evidence"]["output_contract"] = "finance-decision-v2"
    elif change == "wrong_command":
        fx.conn.execute("update jobs set command_type='review_case' where id=%s", (fx.job["id"],))
    elif change == "revoked_editor":
        fx.conn.execute(
            "update memberships set active=false where organization_id=%s and user_id=%s",
            (fx.org, fx.users[0]),
        )
    elif change == "read_version":
        fx.payload["tool_events"][0]["result"]["version"] = 2
        fx.payload["output"]["consulted_source_refs"][0]["version"] = 2
        response["consulted_source_refs"][0]["version"] = 2
    elif change == "foreign_source":
        foreign_run = uuid4()
        fx.conn.execute(
            "insert into demo_runs(id,organization_id,name) values(%s,%s,'Foreign source fixture')",
            (foreign_run, fx.org),
        )
        foreign_tools = FinanceToolClient(Scope(fx.org, foreign_run), fx.tools._client)
        foreign = await foreign_tools.call(
            "record_source",
            {
                "external_id": "foreign-consulted",
                "version": 1,
                "source_type": "test_fixture",
                "content_sha256": "a" * 64,
                "idempotency_key": "foreign-consulted",
            },
        )
        fx.payload["tool_events"][0]["result"]["id"] = foreign["id"]
        fx.payload["output"]["evidence_source_ids"] = [foreign["id"]]
        fx.payload["output"]["consulted_source_refs"][0]["id"] = foreign["id"]
        response["consulted_source_ids"] = [foreign["id"]]
        response["consulted_source_refs"][0]["id"] = foreign["id"]
    elif change == "demo_owner":
        fx.conn.execute(
            "update demo_runs set is_demo=true,owner_user_id=%s where id=%s", (fx.users[1], fx.run)
        )
    elif change == "cancelled_job":
        fx.conn.execute("update jobs set status='cancelled' where id=%s", (fx.job["id"],))
    if change in {
        "failed_read",
        "invented_read",
        "wrong_contract",
        "read_version",
        "foreign_source",
    }:
        await capture_new_fixture_trace(fx)
    fx.args[7] = Jsonb(response)
    with pytest.raises(
        (
            psycopg.errors.CheckViolation,
            psycopg.errors.SerializationFailure,
            psycopg.errors.InsufficientPrivilege,
        )
    ):
        fx.conn.execute(QUERY, fx.args)
    assert (
        "director_responses"
        not in (await fx.tools.call("get_case", {"case_id": fx.before["id"]}))["data"]
    )


@pytest.mark.asyncio
async def test_rpc_denies_browser_role_and_evaluation_and_rechecks_idempotent_editor_authority(
    state,
):
    fx = await response_fixture(state)
    identity(fx.conn, fx.users[0])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        fx.conn.execute(QUERY, fx.args)
    identity(fx.conn, service=True)
    evaluation = fx.tools.for_evaluation(
        {"organization": {"id": str(fx.org)}, "run": {"id": str(fx.run)}}
    )
    with pytest.raises(FinanceError):
        await evaluation.call("record_director_response", {})
    assert (await persist_director_response(fx.tools, fx.before, fx.outcome, fx.job))[
        "status"
    ] == "persisted"
    fx.conn.execute(
        "update memberships set active=false where organization_id=%s and user_id=%s",
        (fx.org, fx.users[0]),
    )
    denied = await persist_director_response(fx.tools, fx.before, fx.outcome, fx.job)
    assert denied["status"] == "blocked"


@pytest.mark.asyncio
async def test_thread_reads_are_consulted_and_no_document_read_is_valid_for_record_queries(state):
    fx = await response_fixture(state)
    fx.payload["tool_events"] = [
        {
            "name": "read_thread",
            "result": {"documents": [fx.events[0]["result"], fx.events[0]["result"]]},
        }
    ]
    await capture_new_fixture_trace(fx)
    assert (await persist_director_response(fx.tools, fx.before, fx.outcome, fx.job))[
        "status"
    ] == "persisted"
    current = await fx.tools.call("get_case", {"case_id": fx.before["id"]})
    empty = await response_fixture(state, tools=fx.tools, before=current)
    empty.payload["tool_events"] = [
        {"name": "get_financial_position", "result": {"cash_minor": None}}
    ]
    empty.payload["output"]["evidence_source_ids"] = []
    empty.payload["output"]["consulted_source_refs"] = []
    await capture_new_fixture_trace(empty)
    assert (await persist_director_response(empty.tools, empty.before, empty.outcome, empty.job))[
        "status"
    ] == "persisted"
    current = await fx.tools.call("get_case", {"case_id": fx.before["id"]})
    assert current["data"]["director_responses"][-1]["consulted_source_ids"] == []

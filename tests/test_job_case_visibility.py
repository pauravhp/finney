"""Real PostgreSQL authorization/projection checks, without providers."""
import json
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_finance_postgres import call, identity
from test_finance_postgres import database as database  # noqa: PLC0414
from test_finance_postgres import state as state  # noqa: PLC0414


def snapshot(conn, org, run):
    return conn.execute("select get_finance_snapshot(%s,%s)", (org, run)).fetchone()[0]


def test_actual_admitted_review_and_director_jobs_show_safe_case_association(state):
    conn, org, run, users = state
    case = call(conn, org, run, "record_case", {"title": "Invoice", "idempotency_key": "visible-case"})
    identity(conn, users[0])
    ids = []
    for command in ("review_case", "director_message"):
        payload = {"case_id": case["id"]}
        if command == "director_message":
            payload["message"] = "PRIVATE_DIRECTOR_MESSAGE_SENTINEL"
        ids.append(conn.execute("select enqueue_finance_command(%s,%s,%s,%s,%s)",
                               (org, run, command, Jsonb(payload), "visible-" + command)).fetchone()[0])
    rows = {row["id"]: row for row in snapshot(conn, org, run)["jobs"]}
    expected_fields = {"id", "command_type", "status", "attempts", "error_code", "created_at", "updated_at", "case_id"}
    for job_id in ids:
        assert rows[str(job_id)]["case_id"] == case["id"]
        assert rows[str(job_id)]["status"] == "queued"
        assert set(rows[str(job_id)]) == expected_fields
    encoded = json.dumps(list(rows.values()))
    assert "PRIVATE_DIRECTOR_MESSAGE_SENTINEL" not in encoded and str(users[0]) not in encoded
    conn.execute("reset role")
    conn.execute("update jobs set status='running' where id=%s", (ids[0],))
    identity(conn, users[0])
    assert next(row for row in snapshot(conn, org, run)["jobs"] if row["id"] == str(ids[0]))["case_id"] == case["id"]


def test_projection_rejects_malformed_foreign_or_non_case_payload_without_leaking(state):
    conn, org, run, users = state
    own = call(conn, org, run, "record_case", {"title": "Own case", "idempotency_key": "own"})
    conn.execute("reset role")
    other_run = uuid4()
    conn.execute("insert into demo_runs(id,organization_id,name) values(%s,%s,'Other run')", (other_run, org))
    identity(conn, service=True)
    foreign = call(conn, org, other_run, "record_case", {"title": "Other run case", "idempotency_key": "foreign"})
    conn.execute("reset role")
    inserted = []
    for command, value in (("review_case", "not-a-uuid"), ("director_message", foreign["id"]),
                           ("review_case", {"id": own["id"]}), ("intake", own["id"]),
                           ("director_message", str(uuid4())), ("review_case", None)):
        job_id = uuid4()
        conn.execute("insert into jobs(id,organization_id,run_id,command_type,payload,request_payload,idempotency_key) values(%s,%s,%s,%s,%s,%s,%s)",
                     (job_id, org, run, command, Jsonb({"case_id": value, "secret": "PRIVATE_PAYLOAD_SENTINEL"}),
                      Jsonb({"case_id": own["id"]}), str(job_id)))
        inserted.append(str(job_id))
    valid_id = uuid4()
    conn.execute("insert into jobs(id,organization_id,run_id,command_type,payload,request_payload,idempotency_key) values(%s,%s,%s,'review_case',%s,%s,%s)",
                 (valid_id, org, run, Jsonb({"case_id": own["id"].upper()}), Jsonb({"case_id": foreign["id"]}), str(valid_id)))
    identity(conn, users[0])
    rows = {row["id"]: row for row in snapshot(conn, org, run)["jobs"]}
    assert all(rows[job_id]["case_id"] is None for job_id in inserted)
    assert rows[str(valid_id)]["case_id"] == own["id"]
    assert foreign["id"] not in json.dumps(rows) and "PRIVATE_PAYLOAD_SENTINEL" not in json.dumps(rows)


def test_snapshot_preserves_scope_authorization_and_private_previous_function(state):
    conn, org, run, _users = state
    outsider = uuid4()
    conn.execute("reset role")
    conn.execute("insert into auth.users(id) values(%s)", (outsider,))
    identity(conn, outsider)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        snapshot(conn, org, run)
    assert not conn.execute("select has_function_privilege('authenticated','public.get_finance_snapshot_v24(uuid,uuid)','EXECUTE')").fetchone()[0]
    conn.execute("reset role")
    conn.execute("set role anon")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        snapshot(conn, org, run)

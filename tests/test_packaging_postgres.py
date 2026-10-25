"""Real LOCAL SQL packaging checks with explicit test-only Supabase platform stubs.

Never uses a hosted Supabase URL. The opt-in local cluster gets a new random test
DB; no pre-existing database is cleared. Identity rows are unit fixtures only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.event_setup import event_sql
from app.setup_sql import migration_sql


@pytest.fixture
def packaging_database():
    url = os.getenv("FINANCE_TEST_DB_URL", "")
    if not url:
        pytest.skip("Explicit local FINANCE_TEST_DB_URL required")
    params = conninfo_to_dict(url)
    if params.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.skip("Packaging SQL tests accept loopback local PostgreSQL only")
    name = "finance_packaging_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
        try:
            params["dbname"] = name
            with psycopg.connect(make_conninfo(**params), autocommit=True) as db:
                db.execute((Path(__file__).parent / "finance_postgres_bootstrap.sql").read_text())
                # Extend only this isolated fixture, leaving shared kernel stubs unchanged.
                db.execute("""
                    alter table auth.users
                      add column email text,
                      add column email_confirmed_at timestamptz,
                      add column is_anonymous boolean not null default false,
                      add column encrypted_password text;
                    create table auth.identities(
                      user_id uuid references auth.users(id), provider text
                    );
                """)
                yield db
        finally:
            admin.execute(sql.SQL("drop database {} with (force)").format(sql.Identifier(name)))


def test_sql_editor_migrations_apply_repeat_and_reject_changed_hash(packaging_database):
    db = packaging_database
    rendered = migration_sql()
    db.execute(rendered)
    first = db.execute("select name,sha256 from finance_schema_migrations order by name").fetchall()
    db.execute(rendered)
    assert (
        db.execute("select name,sha256 from finance_schema_migrations order by name").fetchall()
        == first
    )
    assert len(first) >= 2
    db.execute(
        "update finance_schema_migrations set sha256='modified' where name=%s", (first[0][0],)
    )
    with pytest.raises(psycopg.errors.RaiseException, match="Applied migration changed"):
        db.execute(rendered)
    db.execute("rollback")


def add_email_user(db, user_id):
    """Explicit fixture for an admin-created, confirmed email/password user."""
    db.execute(
        """insert into auth.users(id,email,email_confirmed_at,encrypted_password)
           values(%s,%s,now(),'fixture-password-hash')""",
        (user_id, f"{user_id}@example.invalid"),
    )
    db.execute("insert into auth.identities values(%s,'email')", (user_id,))


def test_shared_event_sql_requires_existing_confirmed_email_users_and_resumes(
    packaging_database, tmp_path
):
    db = packaging_database
    db.execute(migration_sql())
    director, approver = uuid4(), uuid4()
    script = event_sql(
        name="SQL setup test",
        director_user_id=str(director),
        approver_user_id=str(approver),
        currency="USD",
        plan_path=tmp_path / "event.json",
    )
    with pytest.raises(psycopg.errors.RaiseException, match="existing confirmed non-anonymous"):
        db.execute(script)
    db.execute("rollback")
    assert db.execute("select count(*) from organizations").fetchone()[0] == 0
    for identity in (director, approver):
        add_email_user(db, identity)
    db.execute(script)
    db.execute(script)
    assert db.execute("select count(*) from organizations").fetchone()[0] == 1
    assert db.execute("select count(*) from demo_runs where not is_demo").fetchone()[0] == 1
    assert db.execute("select role from memberships order by role").fetchall() == [
        ("approver",),
        ("director",),
    ]


@pytest.mark.parametrize("person", ["director", "approver", "director_only"])
@pytest.mark.parametrize(
    "invalid_state",
    ["unconfirmed", "anonymous", "missing_email", "missing_password", "google_only"],
)
def test_shared_event_sql_refuses_ineligible_email_users(
    packaging_database, tmp_path, person, invalid_state
):
    db = packaging_database
    db.execute(migration_sql())
    users = {"director": uuid4(), "approver": uuid4()}
    for user in users.values():
        add_email_user(db, user)
    user = users["director" if person == "director_only" else person]
    if invalid_state == "google_only":
        db.execute("update auth.identities set provider='google' where user_id=%s", (user,))
    else:
        change = {
            "unconfirmed": "email_confirmed_at=null",
            "anonymous": "is_anonymous=true",
            "missing_email": "email=' '",
            "missing_password": "encrypted_password=''",
        }[invalid_state]
        # The SQL fragment is a fixed test fixture, not caller input.
        db.execute("update auth.users set " + change + " where id=%s", (user,))
    script = event_sql(
        name="Invalid identity test",
        director_user_id=str(users["director"]),
        approver_user_id=None if person == "director_only" else str(users["approver"]),
        currency="USD",
        plan_path=tmp_path / "event.json",
    )
    with pytest.raises(psycopg.errors.RaiseException, match="existing confirmed non-anonymous"):
        db.execute(script)
    db.execute("rollback")
    for table in ("organizations", "memberships", "demo_runs"):
        assert db.execute(sql.SQL("select count(*) from {}").format(sql.Identifier(table))).fetchone()[0] == 0


@pytest.mark.parametrize(
    "approver_configured,existing_member", [(False, "director"), (True, "director"), (True, "approver")]
)
@pytest.mark.parametrize("inactive", [False, True])
def test_shared_event_sql_does_not_promote_existing_unrelated_membership(
    packaging_database, tmp_path, approver_configured, existing_member, inactive
):
    db = packaging_database
    db.execute(migration_sql())
    director, approver = uuid4(), uuid4()
    for user in (director, approver):
        add_email_user(db, user)
    plan_path = tmp_path / "event.json"
    script = event_sql(
        name="Existing membership",
        director_user_id=str(director),
        approver_user_id=str(approver) if approver_configured else None,
        currency="USD",
        plan_path=plan_path,
    )
    org = json.loads(plan_path.read_text())["organization_id"]
    member = director if existing_member == "director" else approver
    role = existing_member if inactive else "finance"
    db.execute("insert into organizations(id,name) values(%s,'Existing membership')", (org,))
    db.execute(
        "insert into memberships(organization_id,user_id,role,active) values(%s,%s,%s,%s)",
        (org, member, role, not inactive),
    )
    with pytest.raises(psycopg.errors.RaiseException, match="Existing memberships differ"):
        db.execute(script)
    db.execute("rollback")
    assert db.execute("select user_id,role,active from memberships").fetchall() == [
        (member, role, not inactive)
    ]
    assert db.execute("select count(*) from demo_runs").fetchone()[0] == 0


def test_director_only_event_is_private_owned_and_empty_and_resumes(packaging_database, tmp_path):
    db = packaging_database
    db.execute(migration_sql())
    director = uuid4()
    plan_path = tmp_path / "event.json"
    script = event_sql(
        name="Private director event", director_user_id=str(director),
        currency="USD", plan_path=plan_path,
    )
    with pytest.raises(psycopg.errors.RaiseException, match="Director needs an existing confirmed"):
        db.execute(script)
    db.execute("rollback")
    assert db.execute("select count(*) from organizations").fetchone()[0] == 0
    add_email_user(db, director)
    db.execute(script)
    db.execute(script)
    plan = json.loads(plan_path.read_text())
    assert db.execute("select count(*) from organizations").fetchone()[0] == 1
    assert db.execute("select id from auth.users").fetchall() == [(director,)]
    assert db.execute("select user_id,role,active from memberships").fetchall() == [
        (director, "director", True),
    ]
    assert db.execute(
        "select id,organization_id,owner_user_id,is_demo,status from demo_runs"
    ).fetchall() == [
        (UUID(plan["run_id"]), UUID(plan["organization_id"]),
         director, False, "active"),
    ]
    for table in ("funds", "ledger_transactions", "ledger_entries", "approvals", "payments"):
        assert db.execute(
            sql.SQL("select count(*) from {}").format(sql.Identifier(table))
        ).fetchone()[0] == 0


@pytest.mark.parametrize("mismatch", ["owner", "demo"])
def test_director_only_event_refuses_mismatched_existing_run(packaging_database, tmp_path, mismatch):
    db = packaging_database
    db.execute(migration_sql())
    director, other = uuid4(), uuid4()
    for user in (director, other):
        add_email_user(db, user)
    script = event_sql(
        name="Owner check", director_user_id=str(director), currency="USD",
        plan_path=tmp_path / "event.json",
    )
    db.execute(script)
    if mismatch == "owner":
        db.execute("update demo_runs set owner_user_id=%s", (other,))
    else:
        db.execute("update demo_runs set is_demo=true")
    with pytest.raises(psycopg.errors.RaiseException, match="Existing event run does not match"):
        db.execute(script)
    db.execute("rollback")
    assert db.execute("select owner_user_id,is_demo from demo_runs").fetchone() == (
        other if mismatch == "owner" else director, mismatch == "demo",
    )

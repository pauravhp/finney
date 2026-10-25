"""Migration upgrade preserves real pre-013 fixture reservations across reset."""

from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from test_finance_postgres import call, identity
from test_finance_postgres import (
    database as database,  # noqa: PLC0414 -- isolated local DB opt-in/administration
)
from test_finance_runtime_guards import attempt_arguments, skill_pair

ROOT = Path(__file__).resolve().parents[1]


def test_upgrade_accounts_for_cancelled_run_and_improvement_usage_without_private_spend(database):
    name = "finance_demo_upgrade_" + uuid4().hex
    admin = psycopg.connect(database, autocommit=True)
    admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    params = conninfo_to_dict(database)
    params["dbname"] = name
    try:
        with psycopg.connect(make_conninfo(**params), autocommit=True) as conn:
            conn.execute((ROOT / "tests/finance_postgres_bootstrap.sql").read_text())
            migrations = sorted((ROOT / "supabase/migrations").glob("*.sql"))
            target = next(path for path in migrations if "013_demo_seed" in path.name)
            for migration in migrations:
                # An upgrade must start before its target, not install future
                # wrapper replacements before the functions they depend on.
                if migration.name < target.name:
                    conn.execute(migration.read_text())
            owner = uuid4()
            conn.execute("insert into auth.users(id) values(%s)", (owner,))
            previous = None
            for _ in range(2):
                identity(conn, owner)
                scope = conn.execute(
                    "select create_finance_demo('Pre-upgrade fixture',%s)", (previous,)
                ).fetchone()[0]
                previous = scope["run_id"]
                identity(conn, service=True)
                for _ in range(3):
                    assert call(
                        conn,
                        scope["organization_id"],
                        scope["run_id"],
                        "reserve_run_inference",
                        {"reservation_id": str(uuid4()), "max_model_calls": 40},
                    )["claimed"]
            identity(conn, owner)
            scope = conn.execute(
                "select create_finance_demo('Pre-upgrade improvement',%s)", (previous,)
            ).fetchone()[0]
            identity(conn, service=True)
            baseline, _candidate = skill_pair(conn, scope["organization_id"], scope["run_id"])
            assert call(
                conn,
                scope["organization_id"],
                scope["run_id"],
                "claim_improvement_attempt",
                attempt_arguments(conn, scope["organization_id"], scope["run_id"], baseline),
            )["claimed"]
            conn.execute("reset role")
            private = uuid4()
            conn.execute(
                "insert into demo_runs(id,organization_id,name) values(%s,%s,'Private fixture')",
                (private, scope["organization_id"]),
            )
            identity(conn, service=True)
            assert call(
                conn,
                scope["organization_id"],
                private,
                "reserve_run_inference",
                {"reservation_id": str(uuid4()), "max_model_calls": 40},
            )["claimed"]
            conn.execute("reset role")
            conn.execute(target.read_text())
            for migration in migrations:
                if migration.name > target.name:
                    conn.execute(migration.read_text())
            assert conn.execute(
                "select reserved_model_calls,model_call_limit from finance_demo_owner_limits where user_id=%s",
                (owner,),
            ).fetchone() == (280, 120)
            assert (
                conn.execute(
                    "select reserved_model_calls from finance_demo_daily_limits"
                ).fetchone()[0]
                == 280
            )
            identity(conn, owner)
            reset = conn.execute(
                "select create_finance_demo('Post-upgrade reset',%s)", (scope["run_id"],)
            ).fetchone()[0]
            identity(conn, service=True)
            denied = call(
                conn,
                reset["organization_id"],
                reset["run_id"],
                "reserve_run_inference",
                {"reservation_id": str(uuid4()), "max_model_calls": 1},
            )
            assert denied["reason"] == "demo_owner_lifetime_model_budget_exhausted"
    finally:
        admin.execute(sql.SQL("drop database {} with (force)").format(sql.Identifier(name)))
        admin.close()

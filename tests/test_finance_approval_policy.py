"""Real isolated LOCAL SQL; fixture identities/wallet replies are not live humans/provider execution."""
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from test_finance_postgres import (
    approve,
    call,
    identity,
    opening,
    proposal,
)
from test_finance_postgres import (
    database as database,  # noqa: PLC0414 -- pytest fixture registration
)
from test_finance_postgres import (
    state as state,  # noqa: PLC0414 -- pytest fixture registration
)

from app.finance.tools import FinanceToolClient
from app.finance.types import FinanceError, Scope


def director(conn, org, user):
    conn.execute("reset role")
    conn.execute("update memberships set role='director' where organization_id=%s and user_id=%s", (org, user))
    identity(conn, user)


def set_policy(conn, org, run, count, revision=None):
    if revision is None:
        revision = conn.execute("select revision from demo_runs where id=%s", (run,)).fetchone()[0]
    return conn.execute("select set_event_approval_policy(%s,%s,%s,%s)", (org, run, count, revision)).fetchone()[0]


def reserve(conn, org, run, p, key="reserve-policy"):
    identity(conn, service=True)
    return call(conn, org, run, "reserve_approved_payment", {"proposal_id": str(p["id"]), "idempotency_key": key})


def test_policy_defaults_director_setter_cas_and_noop(state):
    conn, org, run, users = state
    snapshot = conn.execute("select get_finance_snapshot(%s,%s)", (org, run)).fetchone()[0]
    assert snapshot["run"]["required_payment_approvals"] == 2
    assert snapshot["run"]["approval_policy_version"] == 1
    director(conn, org, users[0])
    changed = set_policy(conn, org, run, 1, 0)
    assert changed == {"organization_id": str(org), "run_id": str(run), "required_payment_approvals": 1,
                       "approval_policy_version": 2, "revision": 1}
    assert set_policy(conn, org, run, 1, 1) == changed
    with pytest.raises(psycopg.errors.SerializationFailure, match="approval policy revision changed"):
        set_policy(conn, org, run, 2, 0)
    assert set_policy(conn, org, run, 2, 1)["approval_policy_version"] == 3
    assert conn.execute("select count(*) from audit_events where run_id=%s and event_type='approval_policy_changed'", (run,)).fetchone()[0] == 2


@pytest.mark.parametrize("value", [None, 0, 3, -1])
def test_director_cannot_choose_unsupported_count(state, value):
    conn, org, run, users = state
    director(conn, org, users[0])
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="must be 1 or 2"):
        set_policy(conn, org, run, value, 0)


@pytest.mark.parametrize("role", ["finance", "approver", "viewer", "inactive_director", "outsider", "service", "service_director", "anon"])
def test_setter_excludes_every_non_director_authority(state, role):
    conn, org, run, users = state
    conn.execute("reset role")
    if role in {"finance", "approver", "viewer", "inactive_director"}:
        conn.execute("update memberships set role=%s,active=%s where organization_id=%s and user_id=%s", ("director" if role == "inactive_director" else role, role != "inactive_director", org, users[0]))
        identity(conn, users[0])
    elif role == "outsider":
        identity(conn, uuid4())
    elif role == "anon":
        conn.execute("select set_config('request.jwt.claim.role','anon',false)")
        conn.execute("set role anon")
    else:
        conn.execute("update memberships set role='director' where organization_id=%s and user_id=%s", (org, users[0]))
        identity(conn, users[0] if role == "service_director" else None, service=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        set_policy(conn, org, run, 1, 0)


@pytest.mark.asyncio
async def test_solo_director_self_approves_and_executor_sends_once_on_real_sql(state):
    from app.payments.executor import PaymentExecutor
    from app.payments.types import NETWORK, build_testnet_payment_action

    conn, org, run, users = state
    opening(conn, org, run)
    director(conn, org, users[0])
    conn.execute("reset role")
    conn.execute("update memberships set active=false where organization_id=%s and user_id<>%s", (org, users[0]))
    identity(conn, users[0])
    set_policy(conn, org, run, 1)
    identity(conn, service=True)
    from test_finance_postgres import source_ref
    obligation = call(conn, org, run, "propose_obligation_update", {"title": "Solo expense", "direction": "payable", "currency": "USD", "amount_minor": "1", "source_refs": [source_ref(conn,org,run)], "idempotency_key": "solo-obligation"})
    sender = "0x" + "1" * 40
    action = build_testnet_payment_action(obligation_id=obligation["id"], obligation_version=1, amount_minor="1", destination="0x" + "2" * 40, sender=sender)
    p = call(conn, org, run, "create_approval_request", {"action": action, "proposed_by": str(users[0]), "idempotency_key": "solo-proposal"})
    assert p["required_approvals"] == 1 and p["approval_policy_version"] == 2
    assert approve(conn, users[0], p)["approval_count"] == 1
    assert approve(conn, users[0], p)["required_approvals"] == 1
    identity(conn, service=True)

    class Tools:
        prepare_only = False

        async def call(self, name, args):
            return call(conn, org, run, name, args)

    class Wallet:
        configured = True
        sends = 0

        async def verify_sender(self, sender):
            pass

        async def send(self, intent):
            self.sends += 1
            identity(conn, users[0])
            with pytest.raises(psycopg.errors.CheckViolation, match="unsettled payments"):
                set_policy(conn, org, run, 2)
            identity(conn, service=True)
            return {"transactionHash": "0x" + "a" * 64}

    class Verifier:
        async def network_status(self):
            return {"network": NETWORK}

        async def verify(self, reference, intent):
            return {**action, "provider_reference": reference, "status": "confirmed"}

    wallet = Wallet()
    executor = PaymentExecutor(Tools(), wallet, Verifier(), sender_address=sender)
    first = await executor.execute(p["id"])
    second = await executor.execute(p["id"])
    assert first["status"] == second["status"] == "completed" and second["duplicate"]
    assert wallet.sends == 1
    assert conn.execute("select settled_minor from obligations where id=%s", (obligation["id"],)).fetchone()[0] == 1
    assert conn.execute("select sum(amount_minor) from ledger_entries where run_id=%s and account='cash'", (run,)).fetchone()[0] == 999


def test_single_requires_current_director_and_rechecks_role_at_send(state):
    conn, org, run, users = state
    opening(conn, org, run)
    director(conn, org, users[0])
    set_policy(conn, org, run, 1)
    identity(conn, service=True)
    p = proposal(conn, org, run, users[0])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        approve(conn, users[1], p)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        reserve(conn, org, run, p, "no-director")
    approve(conn, users[0], p)
    pay = reserve(conn, org, run, p)
    conn.execute("update memberships set role='approver' where organization_id=%s and user_id=%s", (org, users[0]))
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="current human approvals"):
        call(conn, org, run, "transition_payment", {"payment_id": pay["id"], "status": "submitting", "idempotency_key": "revoked-director"})
    assert call(conn, org, run, "get_payment_status", {"payment_id": pay["id"]})["status"] == "reserved"
    assert conn.execute("select get_finance_snapshot(%s,%s)", (org, run)).fetchone()[0]["approvals"][0]["approval_count"] == 0


@pytest.mark.parametrize("start,end", [(2, 1), (1, 2)])
def test_changes_stale_proposals_and_never_reuse_decisions_even_after_restoration(state, start, end):
    conn, org, run, users = state
    opening(conn, org, run)
    director(conn, org, users[0])
    if start == 1:
        set_policy(conn, org, run, 1)
    identity(conn, service=True)
    p = proposal(conn, org, run)
    approve(conn, users[0] if start == 1 else users[1], p)
    if start == 2:
        approve(conn, users[2], p)
    identity(conn, users[0])
    changed = set_policy(conn, org, run, end)
    with pytest.raises(psycopg.errors.CheckViolation, match="stale"):
        approve(conn, users[0] if start == 1 else users[1], p)
    with pytest.raises(psycopg.errors.CheckViolation, match="stale"):
        reserve(conn, org, run, p)
    identity(conn, users[0])
    restored = set_policy(conn, org, run, start)
    assert restored["approval_policy_version"] == changed["approval_policy_version"] + 1
    with pytest.raises(psycopg.errors.CheckViolation, match="stale"):
        approve(conn, users[0] if start == 1 else users[1], p)
    with pytest.raises(psycopg.errors.CheckViolation, match="stale"):
        reserve(conn, org, run, p, "after-restoration")
    fresh = call(conn, org, run, "create_approval_request", {"action": p["action"], "idempotency_key": "fresh"})
    assert fresh["action_hash"] != p["action_hash"]
    assert call(conn, org, run, "get_approval_status", {"proposal_id": fresh["id"]})["approval_count"] == 0
    assert conn.execute("select count(*) from approvals where proposal_id=%s", (p["id"],)).fetchone()[0] == start
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        reserve(conn, org, run, fresh, "fresh-no-decisions")
    approve(conn, users[0] if start == 1 else users[1], fresh)
    if start == 2:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reserve(conn, org, run, fresh, "restored-two-one-decision")
        approve(conn, users[2], fresh)
    assert reserve(conn, org, run, fresh, "fresh-reserve")["status"] == "reserved"


@pytest.mark.parametrize("status", ["reserved", "submitting", "uncertain", "submitted"])
def test_unsettled_payments_block_policy_change(state, status):
    conn, org, run, users = state
    opening(conn, org, run)
    director(conn, org, users[0])
    identity(conn, service=True)
    p = proposal(conn, org, run)
    approve(conn, users[1], p)
    approve(conn, users[2], p)
    pay = reserve(conn, org, run, p)
    if status != "reserved":
        call(conn, org, run, "transition_payment", {"payment_id": pay["id"], "status": "submitting", "idempotency_key": "claim"})
    if status in {"uncertain", "submitted"}:
        call(conn, org, run, "transition_payment", {"payment_id": pay["id"], "status": status, "provider_reference": "fixture-" + uuid4().hex, "idempotency_key": "inflight"})
    identity(conn, users[0])
    with pytest.raises(psycopg.errors.CheckViolation, match="unsettled payments prevent approval policy change"):
        set_policy(conn, org, run, 1)
    assert set_policy(conn, org, run, 2)["approval_policy_version"] == 1


@pytest.mark.parametrize("field,value", [("required_approvals", 1), ("approval_policy_version", 9)])
def test_proposal_policy_is_immutable_even_to_worker(state, field, value):
    conn, org, run, _ = state
    p = proposal(conn, org, run)
    with pytest.raises(psycopg.errors.CheckViolation, match="immutable"):
        conn.execute(sql.SQL("update action_proposals set {}=%s where id=%s").format(sql.Identifier(field)), (value, p["id"]))


def test_sources_and_kernel_arguments_cannot_choose_policy(state):
    conn, org, run, _ = state
    call(conn, org, run, "record_source", {"external_id": "untrusted-policy", "source_type": "gmail", "content_sha256": "fixture", "metadata": {"required_payment_approvals": 1}, "idempotency_key": "untrusted-policy"})
    p = proposal(conn, org, run)
    forged = call(conn, org, run, "create_approval_request", {"action": p["action"], "required_approvals": 1, "approval_policy_version": 123, "idempotency_key": "forged-policy"})
    assert forged["required_approvals"] == 2 and forged["approval_policy_version"] == 1
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        call(conn, org, run, "set_event_approval_policy", {"required_approvals": 1, "idempotency_key": "forged-operation"})
    assert conn.execute("select required_payment_approvals,approval_policy_version from demo_runs where id=%s", (run,)).fetchone() == (2, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("prepare_only", [False, True])
async def test_actor_and_improver_tool_surface_excludes_policy_setter(prepare_only):
    class NoNetwork:
        async def rpc(self, *args, **kwargs):
            raise AssertionError("policy must not reach service RPC")

    tools = FinanceToolClient(Scope(uuid4(), uuid4()), NoNetwork(), prepare_only=prepare_only)
    with pytest.raises(FinanceError, match="unsupported"):
        await tools.call("set_event_approval_policy", {})
    for field in ["required_approvals", "required_payment_approvals", "approval_policy_version", "p_required_approvals", "p_expected_revision"]:
        with pytest.raises(FinanceError, match="event director"):
            await tools.call("create_approval_request", {field: 1})


def test_service_cannot_bypass_director_policy_via_run_table_writes(state):
    conn, org, run, _ = state
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="authenticated director"):
        conn.execute("update demo_runs set required_payment_approvals=1,approval_policy_version=2,revision=revision+1 where id=%s", (run,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="authenticated director"):
        conn.execute("insert into demo_runs(organization_id,name,required_payment_approvals) values(%s,'Bypass',1)", (org,))
    assert conn.execute("select required_payment_approvals,approval_policy_version from demo_runs where id=%s", (run,)).fetchone() == (2, 1)


def test_idempotent_reservation_and_submission_claim_do_not_renew_authority(state):
    conn, org, run, users = state
    opening(conn, org, run)
    p = proposal(conn, org, run)
    approve(conn, users[1], p)
    approve(conn, users[2], p)
    pay = reserve(conn, org, run, p)
    conn.execute("update memberships set active=false where organization_id=%s and user_id=%s", (org, users[1]))
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="current human approvals"):
        reserve(conn, org, run, p)  # exact historical reservation idempotency key
    conn.execute("update memberships set active=true where organization_id=%s and user_id=%s", (org, users[1]))
    args = {"payment_id": pay["id"], "status": "submitting", "idempotency_key": "one-use-claim"}
    assert call(conn, org, run, "transition_payment", args)["status"] == "submitting"
    with pytest.raises(psycopg.errors.CheckViolation, match="claim already consumed"):
        call(conn, org, run, "transition_payment", args)


@pytest.mark.parametrize("field,value", [("action_hash", "0" * 64), ("approval_policy_version", 99), ("required_approvals", 1)])
def test_forged_stored_policy_or_hash_cannot_approve_or_reserve(state, field, value):
    conn, org, run, users = state
    p = proposal(conn, org, run)
    fields = {"action_hash": p["action_hash"], "approval_policy_version": p["approval_policy_version"], "required_approvals": p["required_approvals"]}
    fields[field] = value
    forged_id = conn.execute("""
        insert into action_proposals(organization_id,run_id,action,action_hash,run_revision,
          required_approvals,approval_policy_version,expires_at,idempotency_key)
        select organization_id,run_id,action,%s,run_revision,%s,%s,expires_at,'forged-stored-policy'
        from action_proposals where id=%s returning id
    """, (fields["action_hash"], fields["required_approvals"], fields["approval_policy_version"], p["id"])).fetchone()[0]
    # Make a valid director for the claimed single mode; freshness still rejects it.
    director(conn, org, users[1])
    with pytest.raises(psycopg.errors.CheckViolation, match="stale"):
        approve(conn, users[1], {"id": forged_id, "action_hash": fields["action_hash"]})
    with pytest.raises(psycopg.errors.CheckViolation, match="stale"):
        reserve(conn, org, run, {"id": forged_id}, "forged-policy-reserve")


def test_concurrent_director_policy_changes_serialize_with_revision_cas(database, state):
    from concurrent.futures import ThreadPoolExecutor

    conn, org, run, users = state
    director(conn, org, users[0])

    def attempt():
        with psycopg.connect(database, autocommit=True) as worker:
            identity(worker, users[0])
            try:
                return set_policy(worker, org, run, 1, 0)
            except psycopg.errors.SerializationFailure:
                return "revision_changed"

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(2)))
    assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
    assert outcomes.count("revision_changed") == 1
    assert conn.execute("select revision,approval_policy_version from demo_runs where id=%s", (run,)).fetchone() == (1, 2)


@pytest.fixture
def legacy_policy_state():
    """Only migrations 001-007; verifies upgrade behavior on actual old records."""
    import os
    from pathlib import Path

    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    admin_url = os.getenv("FINANCE_TEST_DB_URL", "")
    params = conninfo_to_dict(admin_url) if admin_url else {}
    if params.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.skip("Explicit loopback local FINANCE_TEST_DB_URL required")
    name = "finance_policy_upgrade_" + uuid4().hex
    root = Path(__file__).resolve().parents[1]
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
        params["dbname"] = name
        try:
            with psycopg.connect(make_conninfo(**params), autocommit=True) as conn:
                conn.execute((root / "tests/finance_postgres_bootstrap.sql").read_text())
                for migration in sorted((root / "supabase/migrations").glob("*.sql")):
                    if migration.name < "202610250008":
                        conn.execute(migration.read_text())
                org, run = uuid4(), uuid4()
                users = [uuid4() for _ in range(3)]
                conn.execute("insert into organizations(id,name) values(%s,'Upgrade fixture')", (org,))
                conn.execute("insert into demo_runs(id,organization_id,name) values(%s,%s,'Upgrade run')", (run, org))
                for i, user in enumerate(users):
                    conn.execute("insert into auth.users(id) values(%s)", (user,))
                    conn.execute("insert into memberships(organization_id,user_id,role) values(%s,%s,%s)", (org, user, "director" if i == 0 else "approver"))
                identity(conn, service=True)
                opening(conn, org, run)
                p = proposal(conn, org, run)
                approve(conn, users[1], p)
                approve(conn, users[2], p)
                yield conn, org, run, users, p, (root / "supabase/migrations/202610250008_event_approval_policy.sql").read_text()
        finally:
            admin.execute(sql.SQL("drop database {} with (force)").format(sql.Identifier(name)))


def test_upgrade_preserves_old_approvals_as_evidence_and_stales_old_hash(legacy_policy_state):
    conn, org, run, users, p, migration = legacy_policy_state
    conn.execute("reset role")
    conn.execute(migration)
    assert conn.execute("select required_payment_approvals,approval_policy_version from demo_runs where id=%s", (run,)).fetchone() == (2, 1)
    assert conn.execute("select status from action_proposals where id=%s", (p["id"],)).fetchone()[0] == "stale"
    assert conn.execute("select count(*) from approvals where proposal_id=%s", (p["id"],)).fetchone()[0] == 2
    with pytest.raises(psycopg.errors.CheckViolation, match="stale"):
        approve(conn, users[1], p)
    with pytest.raises(psycopg.errors.CheckViolation, match="stale"):
        reserve(conn, org, run, p)


def test_upgrade_refuses_unsettled_old_hash_payment_without_partial_schema(legacy_policy_state):
    conn, org, run, _, p, migration = legacy_policy_state
    reserve(conn, org, run, p)
    conn.execute("reset role")
    with pytest.raises(psycopg.errors.CheckViolation, match="unsettled payments prevent approval policy migration"):
        conn.execute(migration)
    conn.rollback()
    assert conn.execute("select count(*) from information_schema.columns where table_schema='public' and table_name='demo_runs' and column_name='required_payment_approvals'").fetchone()[0] == 0
    assert conn.execute("select status from payments where proposal_id=%s", (p["id"],)).fetchone()[0] == "reserved"

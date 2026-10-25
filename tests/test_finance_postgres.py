"""Real PostgreSQL integration, with explicit test-only Supabase platform stubs.

Opt in using FINANCE_TEST_DB_URL pointing to an isolated admin-capable PostgreSQL.
The fixture creates and drops its own random database, never clears existing data.
This verifies SQL, RLS and concurrency; not hosted Auth/Realtime/Storage delivery.
"""
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def database():
    admin_url = os.getenv("FINANCE_TEST_DB_URL")
    if not admin_url:
        pytest.skip("FINANCE_TEST_DB_URL required; no provider/local-database success implied")
    db_name = "finance_test_" + uuid4().hex
    admin = psycopg.connect(admin_url, autocommit=True)
    admin.execute(sql.SQL("create database {}").format(sql.Identifier(db_name)))
    params = conninfo_to_dict(admin_url)
    params["dbname"] = db_name
    test_url = make_conninfo(**params)
    try:
        with psycopg.connect(test_url, autocommit=True) as conn:
            conn.execute((ROOT / "tests/finance_postgres_bootstrap.sql").read_text())
            for migration in sorted((ROOT / "supabase/migrations").glob("*.sql")):
                conn.execute(migration.read_text())
        yield test_url
    finally:
        admin.execute(sql.SQL("drop database {} with (force)").format(sql.Identifier(db_name)))
        admin.close()


def identity(conn, user=None, *, service=False):
    conn.execute("reset role")
    conn.execute("select set_config('request.jwt.claim.sub',%s,false)", (str(user) if user else "",))
    conn.execute("select set_config('request.jwt.claim.role',%s,false)", ("service_role" if service else "authenticated",))
    conn.execute("set role service_role" if service else "set role authenticated")


def call(conn, org, run, name, arguments):
    return conn.execute("select public.finance_kernel_call(%s,%s,%s,%s)", (org, run, name, Jsonb(arguments))).fetchone()[0]


@pytest.fixture
def state(database):
    with psycopg.connect(database, autocommit=True) as conn:
        users = [uuid4() for _ in range(4)]
        for user in users:
            conn.execute("insert into auth.users(id) values(%s)", (user,))
        org, run = uuid4(), uuid4()
        conn.execute("insert into organizations(id,name) values(%s,'Kernel test')", (org,))
        for i, user in enumerate(users):
            conn.execute("insert into memberships(organization_id,user_id,role) values(%s,%s,%s)", (org,user,"finance" if i==0 else "approver"))
        conn.execute("insert into demo_runs(id,organization_id,name) values(%s,%s,'Test run')", (run,org))
        identity(conn, service=True)
        yield conn, org, run, users


def payable(conn, org, run, amount=300):
    return call(conn,org,run,"propose_obligation_update",{"title":"Verified organizer expense","direction":"payable","currency":"USD","amount_minor":str(amount),"source_refs":[source_ref(conn,org,run)],"idempotency_key":"obligation"})["id"]


def source_ref(conn, org, run, key="payable-source"):
    source = call(conn, org, run, "record_source", {"external_id": key, "source_type": "test_fixture",
        "content_sha256": "a" * 64, "idempotency_key": key})
    return {"id": source["id"], "version": 1}


def opening(conn,org,run,amount=1000):
    return call(conn,org,run,"post_ledger",{"description":"Opening statement","entries":[{"account":"cash","currency":"USD","amount_minor":str(amount)},{"account":"equity","currency":"USD","amount_minor":str(-amount)}],"establish_opening":True,"evidence_status":"statement_confirmed","idempotency_key":"opening"})


def proposal(conn,org,run,proposer=None):
    obligation = payable(conn,org,run)
    return call(conn,org,run,"create_approval_request",{"action":{"type":"payment","amount_minor":"300","currency":"USD","asset":"USDC","network":"base-sepolia","destination":"0xTestRecipient","obligation_id":obligation,"obligation_version":1},"proposed_by":str(proposer) if proposer else None,"idempotency_key":"proposal"})


def approve(conn,user,p):
    identity(conn,user)
    return conn.execute("select approve_finance_proposal(%s,%s,'approve')",(p["id"],p["action_hash"])).fetchone()[0]


def test_unknown_cash_is_null_then_balanced_opening_is_known(state):
    conn,org,run,users=state
    snapshot=conn.execute("select get_finance_snapshot(%s,%s)",(org,run)).fetchone()[0]
    assert snapshot["position"]["cash_minor"] is None
    opening(conn,org,run)
    identity(conn,users[0])
    snapshot=conn.execute("select get_finance_snapshot(%s,%s)",(org,run)).fetchone()[0]
    assert snapshot["position"]["cash_minor"]=="1000"
    assert snapshot["position"]["evidence_status"]=="statement_confirmed"
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("insert into ledger_entries(organization_id,run_id,transaction_id,account,currency,amount_minor) values(%s,%s,%s,'cash','USD',900)",(org,run,uuid4()))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        call(conn,org,run,"record_case",{"title":"unauthorized","idempotency_key":"illegal"})


def test_membership_read_follows_current_identity_on_reused_connection(state):
    conn, org, _, users = state
    for user in (users[0], users[1]):
        identity(conn, user)
        assert conn.execute(
            "select organization_id,user_id from memberships"
        ).fetchall() == [(org, user)]
    identity(conn, uuid4())
    assert conn.execute("select user_id from memberships").fetchall() == []


def test_hermes_mailbox_connect_is_atomic_scoped_and_current_director_only(state):
    conn, org, run, users = state
    statement = "select connect_hermes_gmail(%s,%s,%s,%s,%s,%s)"
    first = (org, run, users[0], "explicit-fixture-ciphertext-" * 4, "one@example.invalid", "label:finance")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(statement, first)  # finance role is not a director
    conn.execute("update memberships set role='director' where user_id=%s", (users[0],))
    identity(conn, users[0])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(statement, first)  # director browser cannot install a grant
    identity(conn, service=True)
    assert conn.execute(statement, first).fetchone()[0]["status"] == "connected"
    conn.execute("update connections set data=data||'{\"history_id\":\"old-cursor\"}'::jsonb")
    second = (*first[:3], "replacement-fixture-ciphertext-" * 4, "two@example.invalid", "label:director-finance")
    conn.execute(statement, second)
    data = conn.execute("select data from connections where run_id=%s", (run,)).fetchone()[0]
    assert data["mailbox"] == "two@example.invalid" and data["history_id"] is None
    assert data["auth_backend"] == "hermes" and data["connected_by"] == str(users[0])
    assert conn.execute("select encrypted_token from connector_secrets where run_id=%s", (run,)).fetchone()[0] == second[3]
    conn.execute("update memberships set active=false where user_id=%s", (users[0],))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(statement, first)
    assert conn.execute("select encrypted_token from connector_secrets where run_id=%s", (run,)).fetchone()[0] == second[3]


@pytest.mark.parametrize("change", ["status='closed'", "expires_at=now()-interval '1 hour'", "is_demo=true,owner_user_id=user_id"])
def test_hermes_mailbox_refuses_inactive_or_public_events(state, change):
    conn, org, run, users = state
    conn.execute("update memberships set role='director' where user_id=%s", (users[0],))
    # All statement fragments above are fixed test fixtures, never user inputs.
    if change.startswith("is_demo"):
        conn.execute("update demo_runs set is_demo=true,owner_user_id=%s where id=%s", (users[0],run))
    else:
        conn.execute("update demo_runs set " + change + " where id=%s", (run,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select connect_hermes_gmail(%s,%s,%s,%s,%s,%s)",
                     (org,run,users[0],"fixture-ciphertext-"*4,"one@example.invalid","label:finance"))


def test_two_distinct_humans_self_approval_hash_and_duplicate_effect(state):
    conn,org,run,users=state
    opening(conn,org,run)
    p=proposal(conn,org,run,users[0])
    identity(conn,users[1])
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        conn.execute("select approve_finance_proposal(%s,'wrong','approve')",(p["id"],))
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        conn.execute("select approve_finance_proposal(%s,null,'approve')",(p["id"],))
    # Promoting proposer role must still not permit self approval.
    conn.execute("reset role")
    conn.execute("update memberships set role='approver' where organization_id=%s and user_id=%s",(org,users[0]))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        approve(conn,users[0],p)
    assert approve(conn,users[1],p)["approval_count"]==1
    assert approve(conn,users[1],p)["approval_count"]==1
    identity(conn,service=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        call(conn,org,run,"reserve_approved_payment",{"proposal_id":p["id"],"idempotency_key":"reserve-too-early"})
    assert approve(conn,users[2],p)["approval_count"]==2
    identity(conn,service=True)
    first=call(conn,org,run,"reserve_approved_payment",{"proposal_id":p["id"],"idempotency_key":"reserve"})
    second=call(conn,org,run,"reserve_approved_payment",{"proposal_id":p["id"],"idempotency_key":"reserve-repeat"})
    assert first["id"]==second["id"]
    assert conn.execute("select count(*) from payments where proposal_id=%s",(p["id"],)).fetchone()[0]==1


def test_source_change_invalidates_approvals_and_idempotency_conflict(state):
    conn,org,run,users=state
    opening(conn,org,run)
    p=proposal(conn,org,run)
    approve(conn,users[1],p)
    approve(conn,users[2],p)
    identity(conn,service=True)
    args={"external_id":"gmail-message","source_type":"gmail","content_sha256":"abc","idempotency_key":"mail"}
    first=call(conn,org,run,"record_source",args)
    assert call(conn,org,run,"record_source",args)==first
    with pytest.raises(psycopg.errors.UniqueViolation):
        call(conn,org,run,"record_source",{**args,"content_sha256":"changed"})
    with pytest.raises(psycopg.errors.CheckViolation,match="stale"):
        call(conn,org,run,"reserve_approved_payment",{"proposal_id":p["id"],"idempotency_key":"stale-reserve"})


def test_unbalanced_privileged_journal_is_rejected_at_commit(state):
    conn,org,run,_=state
    with pytest.raises(psycopg.errors.CheckViolation,match="unbalanced"), conn.transaction():
        transaction=conn.execute("insert into ledger_transactions(organization_id,run_id,description,idempotency_key) values(%s,%s,'invalid','invalid') returning id",(org,run)).fetchone()[0]
        conn.execute("insert into ledger_entries(organization_id,run_id,transaction_id,account,currency,amount_minor) values(%s,%s,%s,'cash','USD',99)",(org,run,transaction))
    assert conn.execute("select count(*) from ledger_transactions where idempotency_key='invalid'").fetchone()[0]==0


def test_demo_rls_and_reset_are_owner_isolated(state):
    conn,_org,_run,users=state
    identity(conn,users[1])
    first=conn.execute("select create_finance_demo('Visitor A',null)").fetchone()[0]
    identity(conn,users[2])
    second=conn.execute("select create_finance_demo('Visitor B',null)").fetchone()[0]
    assert conn.execute("select count(*) from demo_runs where id=%s",(first["run_id"],)).fetchone()[0]==0
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select get_finance_snapshot(%s,%s)",(first["organization_id"],first["run_id"]))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select create_finance_demo('Cross-reset',%s)",(first["run_id"],))
    conn.execute("select create_finance_demo('Visitor B reset',%s)",(second["run_id"],))
    identity(conn,users[1])
    assert conn.execute("select status from demo_runs where id=%s",(first["run_id"],)).fetchone()[0]=="active"


def test_lease_concurrency_and_expired_ack(database,state):
    conn,org,run,users=state
    identity(conn,users[0])
    job_id=conn.execute("select enqueue_finance_command(%s,%s,'review_case','{}','job')",(org,run)).fetchone()[0]
    def lease(worker):
        with psycopg.connect(database,autocommit=True) as c:
            identity(c,service=True)
            return c.execute("select lease_finance_job(%s,10)",(worker,)).fetchone()[0]
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lease,["worker-a","worker-b"]))
    leased=[j for j in results if j is not None and j["id"]==str(job_id)]
    assert len(leased)==1
    job=leased[0]
    identity(conn,service=True)
    with pytest.raises(psycopg.errors.SerializationFailure):
        conn.execute("select finish_finance_job(%s,%s,'{}')",(job_id,uuid4()))
    conn.execute("update jobs set lease_expires_at=now()-interval '1 second' where id=%s",(job_id,))
    with pytest.raises(psycopg.errors.SerializationFailure):
        conn.execute("select finish_finance_job(%s,%s,'{}')",(job_id,job["lease_token"]))
    recovered=lease("worker-recovery")
    assert recovered["lease_token"]!=job["lease_token"] and recovered["attempts"]==2
    conn.execute("select renew_finance_job(%s,%s,120)",(job_id,recovered["lease_token"]))
    with pytest.raises(psycopg.errors.SerializationFailure):
        conn.execute("select renew_finance_job(%s,%s,120)",(job_id,job["lease_token"]))


def test_payment_receipt_must_match_then_ledger_and_obligation_agree(state):
    conn,org,run,users=state
    opening(conn,org,run)
    p=proposal(conn,org,run)
    approve(conn,users[1],p); approve(conn,users[2],p)
    identity(conn,service=True)
    pay=call(conn,org,run,"reserve_approved_payment",{"proposal_id":p["id"],"idempotency_key":"reserve"})
    call(conn,org,run,"transition_payment",{"payment_id":pay["id"],"status":"submitting","idempotency_key":"submitting"})
    call(conn,org,run,"transition_payment",{"payment_id":pay["id"],"status":"submitted","provider_reference":"tx-"+uuid4().hex,"idempotency_key":"submitted"})
    reference=conn.execute("select provider_reference from payments where id=%s",(pay["id"],)).fetchone()[0]
    receipt={"provider_reference":reference,"destination":"wrong","amount_minor":"300","asset":"USDC","network":"base-sepolia","status":"confirmed"}
    with pytest.raises(psycopg.errors.CheckViolation,match="receipt"):
        call(conn,org,run,"confirm_payment",{"payment_id":pay["id"],"receipt":receipt,"idempotency_key":"bad-confirm"})
    receipt["destination"]="0xTestRecipient"
    with pytest.raises(psycopg.errors.CheckViolation,match="receipt"):
        call(conn,org,run,"confirm_payment",{"payment_id":pay["id"],"receipt":{key:value for key,value in receipt.items() if key!='status'},"idempotency_key":"missing-status-confirm"})
    result=call(conn,org,run,"confirm_payment",{"payment_id":pay["id"],"receipt":receipt,"idempotency_key":"confirm"})
    assert result["status"]=="confirmed"
    assert call(conn,org,run,"confirm_payment",{"payment_id":pay["id"],"receipt":receipt,"idempotency_key":"confirm"})==result
    snapshot=conn.execute("select get_finance_snapshot(%s,%s)",(org,run)).fetchone()[0]
    assert snapshot["position"]["cash_minor"]=="700"
    assert snapshot["position"]["committed_minor"]=="0"
    assert snapshot["position"]["available_minor"]=="700"


def test_submission_rechecks_authority_after_reservation(state):
    conn,org,run,users=state
    opening(conn,org,run)
    p=proposal(conn,org,run)
    approve(conn,users[1],p); approve(conn,users[2],p)
    identity(conn,service=True)
    pay=call(conn,org,run,"reserve_approved_payment",{"proposal_id":p["id"],"idempotency_key":"reserve"})
    call(conn,org,run,"record_source",{"external_id":"new evidence","source_type":"gmail","content_sha256":"changed","idempotency_key":"changed-source"})
    with pytest.raises(psycopg.errors.CheckViolation,match="authority"):
        call(conn,org,run,"transition_payment",{"payment_id":pay["id"],"status":"submitting","idempotency_key":"stale-submit"})


def test_atomic_cash_reservations_cannot_overspend(database,state):
    conn,org,run,users=state
    opening(conn,org,run)
    ids=[]
    for index in range(2):
        row=call(conn,org,run,"propose_obligation_update",{"title":f"Payable {index}","direction":"payable","currency":"USD","amount_minor":"600","source_refs":[source_ref(conn,org,run,f"payable-{index}")],"idempotency_key":f"obligation-{index}"})
        ids.append(row["id"])
    proposals=[]
    for index,obligation in enumerate(ids):
        p=call(conn,org,run,"create_approval_request",{"action":{"type":"payment","amount_minor":"600","currency":"USD","asset":"USDC","network":"base-sepolia","destination":f"recipient-{index}","obligation_id":obligation,"obligation_version":1},"idempotency_key":f"proposal-{index}"})
        approve(conn,users[1],p); approve(conn,users[2],p)
        identity(conn,service=True)
        proposals.append(p)
    def reserve(p):
        with psycopg.connect(database,autocommit=True) as other:
            identity(other,service=True)
            try:
                return call(other,org,run,"reserve_approved_payment",{"proposal_id":p["id"],"idempotency_key":"reserve-"+p["id"]})
            except psycopg.errors.CheckViolation:
                return None
    with ThreadPoolExecutor(2) as pool:
        outcomes=list(pool.map(reserve,proposals))
    assert len([x for x in outcomes if x])==1
    assert conn.execute("select sum(amount_minor) from payments where organization_id=%s and run_id=%s",(org,run)).fetchone()[0]==600


def test_skill_bootstrap_promotion_gate_cas_and_rollback(state):
    conn,org,run,_=state
    def save(version,parent=None,status="candidate"):
        return call(conn,org,run,"save_skill_version",{"skill_name":"organizer-expenses","version":version,"artifact_path":f"{org}/{run}/artifacts/hash/{version}.md","content_sha256":"test-only-sha","parent_version_id":parent,"status":status,"idempotency_key":"save-"+version})
    baseline=save("v1",status="baseline")
    call(conn,org,run,"initialize_skill_baseline",{"skill_name":"organizer-expenses","version_id":baseline["id"],"idempotency_key":"initialize"})
    candidate=save("v2",baseline["id"])
    with pytest.raises(psycopg.errors.CheckViolation,match="initialized"):
        call(conn,org,run,"initialize_skill_baseline",{"skill_name":"organizer-expenses","version_id":baseline["id"],"idempotency_key":"reinitialize"})
    evaluation=call(conn,org,run,"record_eval_run",{"skill_name":"organizer-expenses","baseline_version_id":baseline["id"],"candidate_version_id":candidate["id"],"status":"passed","metrics":{"gate_passed":True},"idempotency_key":"forged-eval"})
    activation={"skill_name":"organizer-expenses","version_id":candidate["id"],"expected_active_version_id":baseline["id"],"eval_run_id":evaluation["id"],"idempotency_key":"activate"}
    with pytest.raises(psycopg.errors.CheckViolation,match="gate"):
        call(conn,org,run,"set_active_skill_version",activation)
    # A single positive row plus gate_passed cannot authorize promotion. Build a
    # complete protected manifest/claim and paired results for the positive path.
    from test_finance_runtime_guards import successful_evaluation
    conn.execute("reset role")
    conn.execute("update skill_versions set content_sha256=%s where id=%s", ("b" * 64,candidate["id"]))
    identity(conn,service=True)
    evaluation, _ = successful_evaluation(conn,org,run,baseline,candidate)
    activation["eval_run_id"] = evaluation["id"]
    activated=call(conn,org,run,"set_active_skill_version",activation)
    promoted=conn.execute("select version_id,previous_version_id from promotions where id=%s",(activated["promotion_id"],)).fetchone()
    assert str(promoted[0])==candidate["id"] and str(promoted[1])==baseline["id"]
    replay=call(conn,org,run,"set_active_skill_version",activation)
    assert replay==activated
    assert conn.execute("select count(*) from promotions where version_id=%s and state='promoted'",(candidate["id"],)).fetchone()[0]==1
    rollback=call(conn,org,run,"rollback_skill_version",{"skill_name":"organizer-expenses","version_id":baseline["id"],"expected_active_version_id":candidate["id"],"promotion_id":activated["promotion_id"],"reason":"Regression observed in test fixture","idempotency_key":"rollback"})
    assert rollback["id"]==baseline["id"]
    active=call(conn,org,run,"get_active_skill",{"skill_name":"organizer-expenses"})
    assert active["id"]==baseline["id"]


def test_connection_cursor_metadata_is_durable_and_secrets_are_private(state):
    conn,org,run,users=state
    call(conn,org,run,"set_connection_status",{"provider":"gmail","status":"connected","data":{"mailbox":"test@example.invalid","history_id":"100"},"idempotency_key":"connection-initial"})
    call(conn,org,run,"set_connection_status",{"provider":"gmail","status":"connected","data":{"history_id":"101","last_intake_count":2},"idempotency_key":"connection-next"})
    metadata=conn.execute("select data from connections where organization_id=%s and run_id=%s",(org,run)).fetchone()[0]
    assert metadata["history_id"]=="101" and metadata["mailbox"]=="test@example.invalid"
    conn.execute("insert into connector_secrets(organization_id,run_id,provider,encrypted_token) values(%s,%s,'gmail','explicit-test-fixture-ciphertext')",(org,run))
    identity(conn,users[0])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select encrypted_token from connector_secrets")


def test_source_revision_reopens_only_dependent_cases_and_preserves_exact_money(state):
    conn,org,run,_=state
    source=call(conn,org,run,"record_source",{"external_id":"invoice","source_type":"gmail","content_sha256":"v1","idempotency_key":"source-v1"})
    affected=call(conn,org,run,"record_case",{"title":"Affected invoice","status":"closed","data":{"source_ids":[source["id"]]},"idempotency_key":"affected"})
    unrelated=call(conn,org,run,"record_case",{"title":"Unrelated invoice","status":"closed","data":{},"idempotency_key":"unrelated"})
    call(conn,org,run,"record_source",{"external_id":"invoice","source_type":"gmail","content_sha256":"v2","version":2,"idempotency_key":"source-v2"})
    assert call(conn,org,run,"get_case",{"case_id":affected["id"]})["status"]=="needs_review"
    assert call(conn,org,run,"get_case",{"case_id":unrelated["id"]})["status"]=="closed"
    normalized=conn.execute("select finance_json_money_strings(%s)",(Jsonb({"nested":{"amount_base_units":9007199254740993,"cash_minor":None}}),)).fetchone()[0]
    assert normalized["nested"]["amount_base_units"]=="9007199254740993" and normalized["nested"]["cash_minor"] is None


def test_incoming_receipt_posts_once_and_cannot_be_reused_by_another_run(state):
    conn,org,run,users=state
    from app.payments.types import NETWORK, USDC_ADDRESS
    receipt={"provider_reference":"0x"+uuid4().hex+uuid4().hex,"log_index":0,"amount_minor":"1","amount_base_units":"10000",
             "network":NETWORK,"token_address":USDC_ADDRESS,"asset":"USDC","asset_decimals":6,"status":"confirmed",
             "verification":"independent_json_rpc_receipt","sender":"0x"+"1"*40,"destination":"0x"+"2"*40}
    params=(org,run,Jsonb(receipt),f"{org}/{run}/artifacts/{'0'*64}/receipt.json","0"*64)
    first=conn.execute("select record_finance_income(%s,%s,%s,%s,%s)",params).fetchone()[0]
    second=conn.execute("select record_finance_income(%s,%s,%s,%s,%s)",params).fetchone()[0]
    assert not first["duplicate"] and second["duplicate"] and first["ledger_transaction_id"]==second["ledger_transaction_id"]
    assert conn.execute("select sum(amount_minor) from ledger_entries where organization_id=%s and run_id=%s and account='cash'",(org,run)).fetchone()[0]==1
    conn.execute("reset role")
    other=uuid4()
    conn.execute("insert into demo_runs(id,organization_id,name) values(%s,%s,'Other receipt scope')",(other,org))
    identity(conn,service=True)
    with pytest.raises(psycopg.errors.UniqueViolation,match="attributed"):
        conn.execute("select record_finance_income(%s,%s,%s,%s,%s)",(org,other,Jsonb(receipt),f"{org}/{other}/artifacts/{'0'*64}/receipt.json","0"*64))
    identity(conn,users[0])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select record_finance_income(%s,%s,%s,%s,%s)",params)


def test_income_rejects_wrong_network_and_fractional_cent_conversion_atomically(state):
    conn,org,run,_=state
    from app.payments.types import NETWORK, USDC_ADDRESS
    valid={"provider_reference":"0x"+uuid4().hex+uuid4().hex,"log_index":0,"amount_minor":"1","amount_base_units":"10000",
             "network":NETWORK,"token_address":USDC_ADDRESS,"asset":"USDC","asset_decimals":6,"status":"confirmed",
             "verification":"independent_json_rpc_receipt","sender":"0x"+"1"*40,"destination":"0x"+"2"*40}
    for mutation in [{"network":"eip155:8453"},{"amount_base_units":"10001"},{"status":None}]:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("select record_finance_income(%s,%s,%s,%s,%s)",(org,run,Jsonb({**valid,**mutation}),f"{org}/{run}/artifacts/{'0'*64}/receipt.json","0"*64))
    assert conn.execute("select count(*) from ledger_transactions where organization_id=%s and run_id=%s",(org,run)).fetchone()[0]==0


@pytest.mark.asyncio
async def test_competing_payment_executors_only_one_requests_remote_send(database,state):
    """Real SQL claim boundary, explicitly fake remote wallet with a delayed reply."""
    from app.payments.executor import PaymentExecutor
    from app.payments.types import NETWORK, build_testnet_payment_action
    conn,org,run,users=state
    opening(conn,org,run)
    obligation=payable(conn,org,run)
    sender="0x"+"1"*40
    approved=build_testnet_payment_action(obligation_id=obligation,obligation_version=1,amount_minor="1",destination="0x"+"2"*40,sender=sender)
    p=call(conn,org,run,"create_approval_request",{"action":approved,"idempotency_key":"concurrent-proposal"})
    approve(conn,users[1],p);approve(conn,users[2],p)
    identity(conn,service=True)
    started,release=asyncio.Event(),asyncio.Event()
    class SQLTools:
        prepare_only=False
        def __init__(self,connection): self.connection=connection
        async def call(self,name,args): return call(self.connection,org,run,name,args)
    class Wallet:
        configured=True
        sends=0
        async def verify_sender(self,value): return None
        async def send(self,intent):
            self.sends+=1;started.set();await release.wait()
            return {"requestId":"explicit-local-test-request","approvalUrl":"https://keys.coinbase.com/approve/test-only"}
    class Verifier:
        async def network_status(self): return {"network":NETWORK}
    wallet=Wallet()
    with psycopg.connect(database,autocommit=True) as other:
        identity(other,service=True)
        executor1=PaymentExecutor(SQLTools(conn),wallet,Verifier(),sender_address=sender)
        executor2=PaymentExecutor(SQLTools(other),wallet,Verifier(),sender_address=sender)
        first_task=asyncio.create_task(executor1.execute(p["id"]))
        await asyncio.wait_for(started.wait(),timeout=5)
        second=await executor2.execute(p["id"])
        release.set()
        first=await first_task
    assert wallet.sends==1 and first["reason"]=="awaiting_coinbase_wallet_approval"
    assert second["reason"]=="uncertain_submission_do_not_resend"


@pytest.mark.parametrize("amount",[0,12345])
def test_director_attested_opening_cash_supports_zero_and_exact_replay(state,amount):
    conn,org,run,users=state
    conn.execute("reset role")
    conn.execute("update memberships set role='director' where organization_id=%s and user_id=%s",(org,users[0]))
    identity(conn,service=True)
    cutoff=datetime.now(UTC)
    source=call(conn,org,run,"record_source",{"external_id":"opening-attestation","source_type":"owner_attestation","content_sha256":"explicit-test-hash",
        "metadata":{"evidence_status":"owner_attested","attested_by":str(users[0]),"amount_minor":str(amount),"currency":"USD","as_of":cutoff.isoformat()},"idempotency_key":"opening-evidence"})
    params=(org,run,users[0],amount,"USD",cutoff,source["id"],"opening-attestation")
    first=conn.execute("select establish_finance_opening_cash(%s,%s,%s,%s,%s,%s,%s,%s)",params).fetchone()[0]
    second=conn.execute("select establish_finance_opening_cash(%s,%s,%s,%s,%s,%s,%s,%s)",params).fetchone()[0]
    assert first==second
    snapshot=conn.execute("select get_finance_snapshot(%s,%s)",(org,run)).fetchone()[0]
    assert snapshot["position"]["cash_minor"]==str(amount) and snapshot["position"]["evidence_status"]=="owner_attested"
    assert conn.execute("select count(*) from ledger_transactions where organization_id=%s and run_id=%s",(org,run)).fetchone()[0]==(0 if amount==0 else 1)
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("select establish_finance_opening_cash(%s,%s,%s,%s,%s,%s,%s,%s)",(org,run,users[0],amount+1,"USD",cutoff,source["id"],"opening-attestation"))
    with pytest.raises(psycopg.errors.CheckViolation,match="already established"):
        conn.execute("select establish_finance_opening_cash(%s,%s,%s,%s,%s,%s,%s,%s)",(org,run,users[0],amount,"USD",cutoff,source["id"],"second-opening"))


def test_opening_cash_requires_real_director_and_exact_immutable_attestation(state):
    conn,org,run,users=state
    cutoff=datetime.now(UTC)
    source=call(conn,org,run,"record_source",{"external_id":"bad-attestation","source_type":"owner_attestation","content_sha256":"explicit-test-hash",
        "metadata":{"evidence_status":"owner_attested","attested_by":str(users[0]),"amount_minor":"500","currency":"USD","as_of":cutoff.isoformat()},"idempotency_key":"bad-evidence"})
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select establish_finance_opening_cash(%s,%s,%s,500,'USD',%s,%s,'opening')",(org,run,users[0],cutoff,source["id"]))
    conn.execute("reset role");conn.execute("update memberships set role='director' where organization_id=%s and user_id=%s",(org,users[0]))
    identity(conn,service=True)
    with pytest.raises(psycopg.errors.CheckViolation,match="exact opening"):
        conn.execute("select establish_finance_opening_cash(%s,%s,%s,501,'USD',%s,%s,'opening')",(org,run,users[0],cutoff,source["id"]))
    assert not conn.execute("select cash_established from demo_runs where id=%s",(run,)).fetchone()[0]
    identity(conn,users[0])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select establish_finance_opening_cash(%s,%s,%s,500,'USD',%s,%s,'opening')",(org,run,users[0],cutoff,source["id"]))


def test_storage_positive_read_and_other_scope_private_helpers_are_isolated(state):
    conn,org,run,users=state
    conn.execute("reset role")
    # Explicit local Supabase-platform grants: production already manages these.
    conn.execute("grant usage on schema storage to authenticated")
    conn.execute("grant select on storage.objects to authenticated")
    other_org,other_run,other_demo=uuid4(),uuid4(),uuid4()
    conn.execute("insert into organizations(id,name) values(%s,'Other organization')",(other_org,))
    conn.execute("insert into demo_runs(id,organization_id,name) values(%s,%s,'Other organization run')",(other_run,other_org))
    conn.execute("insert into demo_runs(id,organization_id,name,is_demo,owner_user_id) values(%s,%s,'Other visitor',true,%s)",(other_demo,org,users[1]))
    names=[f"{org}/{run}/artifacts/owned.txt",f"{other_org}/{other_run}/artifacts/other-org.txt",f"{org}/{other_demo}/artifacts/other-visitor.txt"]
    for name in names:
        conn.execute("insert into storage.objects(id,name,bucket_id) values(%s,%s,'finance-artifacts')",(uuid4(),name))
    identity(conn,users[0])
    readable=conn.execute("select name from storage.objects order by name").fetchall()
    assert readable==[(names[0],)], "authorized Storage read must succeed without exposing another scope"
    for table in ("connector_secrets","oauth_pending","finance_operations","trace_events"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(sql.SQL("select * from {}").format(sql.Identifier(table)))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select finance_audit(%s,%s,'forged-event','{}')",(org,run))


def prepared_review_context(conn,org,run,*,case_status="open"):
    source=call(conn,org,run,"record_source",{"external_id":"review-invoice","source_type":"gmail","content_sha256":"explicit-fixture-hash","idempotency_key":"review-source"})
    case=call(conn,org,run,"record_case",{"title":"Review invoice","status":case_status,"data":{"source_ids":[source["id"]],"evidence_state":"reported","keep":"original"},"idempotency_key":"review-case"})
    job_id=uuid4()
    conn.execute("insert into jobs(id,organization_id,run_id,command_type,payload,idempotency_key) values(%s,%s,%s,'review_case',%s,'review-job')",(job_id,org,run,Jsonb({"case_id":case["id"]})))
    output={"decision":"investigate_missing_payer","evidence_source_ids":[source["id"]],"clarification":"Who personally paid this invoice?","proposed_action":None,"explanation":"Payer evidence is missing.","blocking_requirements":[]}
    trace=call(conn,org,run,"record_trace",{"case_id":case["id"],"event_type":"actor_completed","payload":{"job_id":str(job_id),"skill_version":str(uuid4()),"output":output,"tool_events":[]},"idempotency_key":"actor-completion"})
    finding={**output,"provenance":{"job_id":str(job_id),"actor_trace_id":trace["id"],"source_case_version":1}}
    return source,case,job_id,trace,finding


@pytest.mark.parametrize("case_status",["open","closed"])
def test_prepared_review_annotation_is_atomic_and_preserves_fresh_payment_authority(state,case_status):
    conn,org,run,users=state
    source,case,job_id,trace,finding=prepared_review_context(conn,org,run,case_status=case_status)
    opening(conn,org,run)
    p=proposal(conn,org,run)
    revision=conn.execute("select revision from demo_runs where id=%s",(run,)).fetchone()[0]
    params=(org,run,case["id"],1,[source["id"]],trace["id"],job_id,Jsonb(finding),"case-review:"+str(job_id))
    statement="select record_finance_case_review(%s,%s,%s,%s,%s,%s,%s,%s,%s)"
    first=conn.execute(statement,params).fetchone()[0]
    assert conn.execute(statement,params).fetchone()[0]==first
    assert conn.execute("select revision from demo_runs where id=%s",(run,)).fetchone()[0]==revision
    updated=call(conn,org,run,"get_case",{"case_id":case["id"]})
    assert updated["status"]==("closed" if case_status=="closed" else "awaiting_evidence") and updated["version"]==2
    assert updated["data"]["keep"]=="original" and updated["data"]["evidence_state"]=="reported"
    assert updated["data"]["finding"]["verification"]=="unverified_model_recommendation"
    assert updated["data"]["finding"]["effects_completed"] is False
    assert conn.execute("select count(*) from trace_events where run_id=%s and event_type='case_review_persisted'",(run,)).fetchone()[0]==1
    approve(conn,users[1],p);approve(conn,users[2],p)
    identity(conn,service=True)
    payment=call(conn,org,run,"reserve_approved_payment",{"proposal_id":p["id"],"idempotency_key":"review-then-reserve"})
    assert payment["status"]=="reserved"
    identity(conn,users[0])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):conn.execute(statement,params)


def test_prepared_review_rejects_changed_sources_and_forged_actor_output(state):
    conn,org,run,_=state
    source,case,job_id,trace,finding=prepared_review_context(conn,org,run)
    statement="select record_finance_case_review(%s,%s,%s,%s,%s,%s,%s,%s,%s)"
    params=(org,run,case["id"],1,[source["id"]],trace["id"],job_id,Jsonb({**finding,"explanation":"Forged output"}),"case-review:"+str(job_id))
    with pytest.raises(psycopg.errors.CheckViolation,match="actual output"):conn.execute(statement,params)
    call(conn,org,run,"record_source",{"external_id":"review-invoice","source_type":"gmail","content_sha256":"revised-fixture-hash","version":2,"idempotency_key":"review-source-v2"})
    params=(org,run,case["id"],1,[source["id"]],trace["id"],job_id,Jsonb(finding),"case-review:"+str(job_id))
    with pytest.raises(psycopg.errors.SerializationFailure,match="context changed"):conn.execute(statement,params)
    updated=call(conn,org,run,"get_case",{"case_id":case["id"]})
    assert "finding" not in updated["data"]

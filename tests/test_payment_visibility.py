"""Actual isolated SQL projections; fixture requests are not Wallet/provider calls."""

import json
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_finance_postgres import approve, call, identity, opening, proposal
from test_finance_postgres import (
    database as database,  # noqa: PLC0414 -- pytest fixture registration
)
from test_finance_postgres import (
    state as state,  # noqa: PLC0414 -- pytest fixture registration
)


def awaiting_wallet(conn,org,run,users,*,solo=False):
    conn.execute("reset role")
    conn.execute("update memberships set role='director' where user_id=%s",(users[0],))
    if solo:
        identity(conn,users[0])
        conn.execute("select set_event_approval_policy(%s,%s,1,0)",(org,run))
    identity(conn,service=True)
    opening(conn,org,run)
    action=proposal(conn,org,run)
    if solo: approve(conn,users[0],action)
    else: approve(conn,users[1],action);approve(conn,users[2],action)
    identity(conn,service=True)
    payment=call(conn,org,run,"reserve_approved_payment",{"proposal_id":action["id"],"idempotency_key":"visibility-reserve"})
    call(conn,org,run,"transition_payment",{"payment_id":payment["id"],"status":"submitting","idempotency_key":"visibility-claim"})
    request_id="fixture-"+str(run)
    call(conn,org,run,"transition_payment",{"payment_id":payment["id"],"status":"uncertain","provider_reference":"wallet-request:"+request_id,"idempotency_key":"visibility-request"})
    result={"status":"blocked","reason":"awaiting_coinbase_wallet_approval","payment_id":payment["id"],"request_id":request_id,
        "approval_url":"https://wallet.example.invalid/approve/"+request_id,"access_token":"FIXTURE-SECRET-NEVER-DISPLAY","output":{"private":"FIXTURE-PRIVATE-OUTPUT"}}
    job=conn.execute("insert into jobs(organization_id,run_id,command_type,payload,status,result,idempotency_key) values(%s,%s,'execute_payment',%s,'blocked',%s,'visibility-job') returning id",
        (org,run,Jsonb({"proposal_id":action["id"]}),Jsonb(result))).fetchone()[0]
    return action,payment,str(job),result


def snapshot(conn,org,run,user=None):
    identity(conn,user,service=user is None)
    return conn.execute("select get_finance_snapshot(%s,%s)",(org,run)).fetchone()[0]


def test_current_eligible_humans_get_only_exact_linked_payment_progress_and_no_raw_results(state):
    conn,org,run,users=state
    action,payment,job,expected=awaiting_wallet(conn,org,run,users)
    for user in (users[0],users[1]):
        result=snapshot(conn,org,run,user)
        projected=result["payments"][0]
        assert projected["id"]==payment["id"] and projected["proposal_id"]==action["id"]
        assert projected["status"]=="uncertain" and projected["can_reconcile"] is True
        assert projected["approval_url"]==expected["approval_url"]
        safe=result["payment_jobs"][0]
        assert safe["id"]==job and safe["proposal_id"]==action["id"] and safe["payment_id"]==payment["id"]
        assert safe["reason"]=="awaiting_coinbase_wallet_approval" and safe["outcome_status"]=="blocked"
        assert set(safe)=={"id","proposal_id","payment_id","status","created_at","updated_at","outcome_status","reason","provider_reference"}
        assert "FIXTURE-SECRET" not in json.dumps(result) and "FIXTURE-PRIVATE" not in json.dumps(result)
        with pytest.raises(psycopg.errors.InsufficientPrivilege): conn.execute("select result from jobs where id=%s",(job,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege): conn.execute("select receipt from payments where id=%s",(payment["id"],))


@pytest.mark.parametrize("role",["finance","viewer","inactive_director","service"])
def test_noneligible_or_service_actor_snapshots_have_no_wallet_capability(state,role):
    conn,org,run,users=state
    awaiting_wallet(conn,org,run,users)
    if role=="service": result=snapshot(conn,org,run)
    else:
        conn.execute("reset role")
        conn.execute("update memberships set role=%s,active=%s where user_id=%s",("director" if role=="inactive_director" else role,role!="inactive_director",users[3]))
        if role=="inactive_director":
            identity(conn,users[3])
            with pytest.raises(psycopg.errors.InsufficientPrivilege): conn.execute("select get_finance_snapshot(%s,%s)",(org,run))
            return
        result=snapshot(conn,org,run,users[3])
        assert conn.execute("select count(*) from payments where run_id=%s",(run,)).fetchone()[0]==0
    assert result["payments"]==[] and result["payment_jobs"]==[]


@pytest.mark.parametrize("url",["http://wallet.example.invalid/a","javascript:alert(1)","https://user:password@wallet.example.invalid/a","https:///bad","https://wallet.example.invalid/a\nAuthorization:secret"])
def test_non_https_or_credential_bearing_or_malformed_provider_links_are_not_exposed(state,url):
    conn,org,run,users=state
    _,_,job,result=awaiting_wallet(conn,org,run,users)
    conn.execute("update jobs set result=%s where id=%s",(Jsonb({**result,"approval_url":url}),job))
    projected=snapshot(conn,org,run,users[0])["payments"][0]
    assert projected["approval_url"] is None and projected["can_reconcile"] is True


@pytest.mark.parametrize("defect",["wrong_payment","wrong_request","stale_authority","revoked_approval"])
def test_wallet_link_needs_actual_payment_request_and_current_human_authority(state,defect):
    conn,org,run,users=state
    _,_,job,result=awaiting_wallet(conn,org,run,users)
    if defect=="wrong_payment": conn.execute("update jobs set result=%s where id=%s",(Jsonb({**result,"payment_id":str(uuid4())}),job))
    elif defect=="wrong_request": conn.execute("update jobs set result=%s where id=%s",(Jsonb({**result,"request_id":"another-request"}),job))
    elif defect=="stale_authority": call(conn,org,run,"record_source",{"external_id":"new-evidence","source_type":"test_fixture","content_sha256":"f"*64,"idempotency_key":"visibility-new-source"})
    else: conn.execute("update memberships set active=false where user_id=%s",(users[1],))
    projected=snapshot(conn,org,run,users[0])["payments"][0]
    assert projected["approval_url"] is None and projected["can_reconcile"] is True


def test_safe_reconciliation_can_be_queued_for_same_proposal_without_new_payment_record(state):
    conn,org,run,users=state
    action,payment,_,_=awaiting_wallet(conn,org,run,users)
    identity(conn,users[0])
    job=conn.execute("select enqueue_finance_command(%s,%s,'execute_payment',%s,'visibility-reconcile')",(org,run,Jsonb({"proposal_id":action["id"]}))).fetchone()[0]
    result=conn.execute("select get_finance_snapshot(%s,%s)",(org,run)).fetchone()[0]
    assert any(item["id"]==str(job) and item["proposal_id"]==action["id"] and item["payment_id"]==payment["id"] for item in result["payment_jobs"])
    assert len(result["payments"])==1 and result["payments"][0]["status"]=="uncertain"
    assert result["payments"][0]["approval_url"] is not None  # preserved after a later poll job


def test_foreign_proposal_job_cannot_leak_another_run_or_result(state):
    conn,org,run,users=state
    awaiting_wallet(conn,org,run,users)
    conn.execute("insert into jobs(organization_id,run_id,command_type,payload,status,result,idempotency_key) values(%s,%s,'execute_payment',%s,'blocked',%s,'foreign-payload-job')",
        (org,run,Jsonb({"proposal_id":str(uuid4())}),Jsonb({"approval_url":"https://foreign.example.invalid/secret","reason":"private content with spaces","provider_reference":"secret"})))
    result=snapshot(conn,org,run,users[0])
    assert len(result["payment_jobs"])==1 and "foreign.example.invalid" not in json.dumps(result)


def test_solo_policy_provider_visibility_is_director_only(state):
    conn,org,run,users=state
    awaiting_wallet(conn,org,run,users,solo=True)
    assert snapshot(conn,org,run,users[0])["payments"][0]["approval_url"] is not None
    assert snapshot(conn,org,run,users[1])["payments"]==[]


def test_confirmed_record_has_no_pending_wallet_capability(state):
    conn,org,run,users=state
    action,payment,_,_=awaiting_wallet(conn,org,run,users)
    reference="0x"+uuid4().hex+uuid4().hex
    call(conn,org,run,"transition_payment",{"payment_id":payment["id"],"status":"submitted","provider_reference":reference,"idempotency_key":"visibility-submitted"})
    receipt={"provider_reference":reference,"destination":action["action"]["destination"],"amount_minor":"300","asset":"USDC","network":"base-sepolia","status":"confirmed"}
    call(conn,org,run,"confirm_payment",{"payment_id":payment["id"],"receipt":receipt,"idempotency_key":"visibility-confirmed"})
    projected=snapshot(conn,org,run,users[0])["payments"][0]
    assert projected["status"]=="confirmed" and projected["approval_url"] is None and projected["can_reconcile"] is False


def test_pending_wallet_link_survives_job_history_limit_and_later_poll_jobs(state):
    conn,org,run,users=state
    action,_,_,expected=awaiting_wallet(conn,org,run,users)
    for index in range(51):
        conn.execute("insert into jobs(organization_id,run_id,command_type,payload,status,result,idempotency_key) values(%s,%s,'execute_payment',%s,'blocked',%s,%s)",
            (org,run,Jsonb({"proposal_id":action["id"]}),Jsonb({"status":"blocked","reason":"wallet_request_not_chain_confirmed"}),"visibility-poll-"+str(index)))
    projected=snapshot(conn,org,run,users[0])
    assert len(projected["payment_jobs"])==50 and projected["payments"][0]["approval_url"]==expected["approval_url"]

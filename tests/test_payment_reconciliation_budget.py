"""Real isolated SQL/executor; every wallet/receipt response is an explicit fixture."""

from uuid import uuid4

import psycopg
import pytest
from test_finance_budget import configure, expense
from test_finance_postgres import approve, call, identity, opening, source_ref
from test_finance_postgres import (
    database as database,  # noqa: PLC0414 -- pytest fixture registration
)
from test_finance_postgres import (
    state as state,  # noqa: PLC0414 -- pytest fixture registration
)

from app.finance.types import Scope
from app.payments.executor import PaymentExecutor
from app.payments.types import NETWORK, build_testnet_payment_action


def prepared(conn,org,run,users):
    opening(conn,org,run)
    line=configure(conn,org,run,users[0])
    obligation=expense(conn,org,run,line)
    sender="0x"+"1"*40
    action=build_testnet_payment_action(obligation_id=obligation["id"],obligation_version=1,amount_minor="300",destination="0x"+"2"*40,sender=sender)
    proposal=call(conn,org,run,"create_approval_request",{"action":action,"idempotency_key":"reconcile-proposal"})
    approve(conn,users[1],proposal);approve(conn,users[2],proposal);identity(conn,service=True)
    return line,action,proposal,sender


def reserve(conn,org,run,proposal):
    return call(conn,org,run,"reserve_approved_payment",{"proposal_id":proposal["id"],"idempotency_key":"payment:"+proposal["id"]+":reserve"})


def advance(conn,org,run,proposal,payment,action,status,tx):
    call(conn,org,run,"transition_payment",{"payment_id":payment["id"],"status":"submitting","idempotency_key":"reconcile-first-claim"})
    if status in {"uncertain","submitted","confirmed"}:
        call(conn,org,run,"transition_payment",{"payment_id":payment["id"],"status":"uncertain" if status=="uncertain" else "submitted",
            "provider_reference":"wallet-request:"+str(uuid4()) if status=="uncertain" else tx,"idempotency_key":"reconcile-provider-result"})
    if status=="confirmed":
        call(conn,org,run,"confirm_payment",{"payment_id":payment["id"],"receipt":{**action,"provider_reference":tx,"status":"confirmed"},"idempotency_key":"reconcile-first-confirm"})


def later_change(conn,org,run,line,defect):
    ref=source_ref(conn,org,run,"unrelated-director-question")
    call(conn,org,run,"record_case",{"title":"Explicit fixture director question","data":{"source_ids":[ref["id"]]},"idempotency_key":"reconcile-question"})
    expense(conn,org,run,None if defect=="unassigned" else line,"900",key="later-budget-change")


class FixtureWallet:
    configured=True
    def __init__(self,tx): self.tx,self.sends,self.polls=tx,0,0
    async def verify_sender(self,sender): assert sender=="0x"+"1"*40
    async def send(self,intent):
        self.sends+=1
        raise AssertionError("Existing-payment reconciliation must never send")
    async def request_status(self,request_id):
        self.polls+=1
        return {"transactionHash":self.tx}


class FixtureVerifier:
    def __init__(self,action): self.action,self.verifies=action,0
    async def network_status(self): return {"network":NETWORK,"verification":"explicit_fixture"}
    async def verify(self,reference,intent):
        self.verifies+=1
        return {**self.action,"provider_reference":reference,"status":"confirmed","verification":"explicit_fixture"}


def executor(conn,org,run,sender,wallet,verifier):
    class SQLTools:
        prepare_only=False
        scope=Scope(org,run)
        async def call(self,name,args): return call(conn,org,run,name,args)
    return PaymentExecutor(SQLTools(),wallet,verifier,sender_address=sender)


@pytest.mark.asyncio
@pytest.mark.parametrize("status",["submitting","uncertain","submitted","confirmed"])
@pytest.mark.parametrize("defect",["unassigned","overcommitted"])
async def test_existing_effect_replay_survives_later_budget_defect_without_resending(state,status,defect):
    conn,org,run,users=state
    line,action,proposal,sender=prepared(conn,org,run,users)
    payment=reserve(conn,org,run,proposal)
    tx="0x"+uuid4().hex+uuid4().hex
    advance(conn,org,run,proposal,payment,action,status,tx)
    later_change(conn,org,run,line,defect)
    wallet,verifier=FixtureWallet(tx),FixtureVerifier(action)
    worker=executor(conn,org,run,sender,wallet,verifier)
    result=await worker.execute(proposal["id"])
    assert wallet.sends==0
    if status=="submitting":
        assert result["reason"]=="uncertain_submission_do_not_resend" and verifier.verifies==0
    else:
        assert result["status"]=="completed"
        assert verifier.verifies==(0 if status=="confirmed" else 1)
        assert wallet.polls==(1 if status=="uncertain" else 0)
        replay=await worker.execute(proposal["id"])
        assert replay["status"]=="completed" and replay["duplicate"] is True and wallet.sends==0
        assert conn.execute("select count(*) from ledger_transactions where run_id=%s and idempotency_key=%s",(run,"payment:"+payment["id"])).fetchone()[0]==1


@pytest.mark.asyncio
@pytest.mark.parametrize("reserved",[False,True])
@pytest.mark.parametrize("defect",["unassigned","overcommitted"])
async def test_new_and_reserved_payments_keep_budget_gates_and_never_send(state,reserved,defect):
    conn,org,run,users=state
    line,action,proposal,sender=prepared(conn,org,run,users)
    payment=reserve(conn,org,run,proposal) if reserved else None
    later_change(conn,org,run,line,defect)
    wallet,verifier=FixtureWallet("0x"+uuid4().hex+uuid4().hex),FixtureVerifier(action)
    with pytest.raises(psycopg.errors.CheckViolation,match="assign every payable|exceed approved allocation"):
        await executor(conn,org,run,sender,wallet,verifier).execute(proposal["id"])
    assert wallet.sends==wallet.polls==verifier.verifies==0
    if payment:
        with pytest.raises(psycopg.errors.CheckViolation,match="assign every payable|exceed approved allocation"):
            call(conn,org,run,"transition_payment",{"payment_id":payment["id"],"status":"submitting","idempotency_key":"blocked-first-send"})


def test_old_internal_entrypoints_remain_denied_and_outer_demo_budget_wrapper_survives(state):
    conn,org,run,_=state
    for name in ("finance_kernel_call_v8","finance_kernel_call_v9","finance_kernel_call_v12"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("select "+name+"(%s,%s,'list_due_work','{}')",(org,run))
    conn.execute("reset role")
    definition=conn.execute("select pg_get_functiondef('finance_kernel_call(uuid,uuid,text,jsonb)'::regprocedure)").fetchone()[0]
    assert "finance_demo_owner_limits" in definition and "finance_demo_daily_limits" in definition


def test_post_submission_receipt_terms_still_must_match_exactly_after_budget_change(state):
    conn,org,run,users=state
    line,action,proposal,_=prepared(conn,org,run,users)
    payment=reserve(conn,org,run,proposal)
    tx="0x"+uuid4().hex+uuid4().hex
    advance(conn,org,run,proposal,payment,action,"submitted",tx)
    later_change(conn,org,run,line,"overcommitted")
    assert reserve(conn,org,run,proposal)["id"]==payment["id"]
    with pytest.raises(psycopg.errors.CheckViolation,match="receipt mismatch"):
        call(conn,org,run,"confirm_payment",{"payment_id":payment["id"],"receipt":{**action,"provider_reference":tx,"status":"confirmed","amount_minor":"299"},"idempotency_key":"wrong-reconcile-receipt"})

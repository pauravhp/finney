"""Actual isolated PostgreSQL checks; all financial/provider inputs are fixtures."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_finance_postgres import call, identity, payable, source_ref
from test_finance_postgres import (
    database as database,  # noqa: PLC0414 -- pytest fixture registration
)
from test_finance_postgres import (
    state as state,  # noqa: PLC0414 -- pytest fixture registration
)

from app.config import Settings
from app.finance.tools import FinanceToolClient
from app.finance.types import FinanceError, Scope
from app.payments.authorization import assert_payment_run_authorized
from app.payments.types import PaymentError


def skill_pair(conn, org, run):
    def save(version, digest, parent=None, status="candidate"):
        return call(conn,org,run,"save_skill_version",{"skill_name":"organizer-expenses","version":version,
            "artifact_path":f"{org}/{run}/artifacts/{digest}/skill.md","content_sha256":digest,
            "parent_version_id":parent,"status":status,"idempotency_key":"skill-"+version})
    baseline=save("baseline","a"*64,status="baseline")
    call(conn,org,run,"initialize_skill_baseline",{"skill_name":"organizer-expenses","version_id":baseline["id"],"idempotency_key":"initialize-test"})
    return baseline,save("candidate","b"*64,parent=baseline["id"])


def attempt_arguments(conn,org,run,baseline,*,key=None):
    key=key or uuid4().hex
    trace=call(conn,org,run,"record_trace",{"event_type":"actor_completed","payload":{"skill_version":baseline["id"]},"idempotency_key":"trace-"+key})
    return {"attempt_id":str(uuid4()),"trace_id":trace["id"],"baseline_version_id":baseline["id"],
        "suite_id":"fixture-protected-suite","suite_manifest_sha256":"c"*64,"evaluator_version":"finance-evaluator-v2","max_model_calls":40,
        "case_manifest":[{"case_key":group,"group":group,"source_snapshot_hash":digest*64}
            for group,digest in (("validation","1"),("regression","2"),("transfer","3"))]}


def successful_evaluation(conn,org,run,baseline,candidate):
    args=attempt_arguments(conn,org,run,baseline)
    assert call(conn,org,run,"claim_improvement_attempt",args)["claimed"]
    assert call(conn,org,run,"claim_improvement_holdout",{"attempt_id":args["attempt_id"],"suite_id":args["suite_id"],"transfer_fingerprints":["3"*64]})["claimed"]
    metadata={key:args[key] for key in ("attempt_id","suite_id","suite_manifest_sha256","evaluator_version")}
    metadata.update({"gate_version":"finance-promotion-v3","gate_passed":True})
    evaluation=call(conn,org,run,"record_eval_run",{"skill_name":"organizer-expenses","baseline_version_id":baseline["id"],
        "candidate_version_id":candidate["id"],"status":"passed","metrics":metadata,"idempotency_key":"full-eval"})
    for item in args["case_manifest"]:
        for variant in ("baseline","candidate"):
            call(conn,org,run,"record_eval_result",{"eval_run_id":evaluation["id"],"case_key":item["case_key"],"variant":variant,
                "passed":True,"hard_invariants_passed":True,"metrics":{"tool_calls":2 if variant=="baseline" else 1},
                "details":{**metadata,**item},"idempotency_key":f"result-{item['case_key']}-{variant}"})
    return evaluation,args


def activate(conn,org,run,baseline,candidate,evaluation):
    return call(conn,org,run,"set_active_skill_version",{"skill_name":"organizer-expenses","version_id":candidate["id"],
        "expected_active_version_id":baseline["id"],"eval_run_id":evaluation["id"],"idempotency_key":"activate-guard"})


@pytest.mark.parametrize("bad_refs",[None,[],[{"id":str(uuid4()),"version":1}],[{"id":"garbage","version":True}]])
def test_obligation_requires_actual_current_scoped_sources(state,bad_refs):
    conn,org,run,_=state
    with pytest.raises(psycopg.errors.CheckViolation,match="source"):
        call(conn,org,run,"propose_obligation_update",{"title":"Invalid source","direction":"payable","currency":"USD","amount_minor":"1","source_refs":bad_refs,"idempotency_key":"bad-source"})


def test_obligation_rejects_stale_cross_run_sources_and_model_confirmation(state):
    conn,org,run,_=state
    ref=source_ref(conn,org,run)
    other_run=uuid4()
    conn.execute("insert into demo_runs(id,organization_id,name) values(%s,%s,'Other run')",(other_run,org))
    foreign=source_ref(conn,org,other_run,"foreign-source")
    args={"title":"Source-backed expense","direction":"payable","currency":"USD","amount_minor":"1","idempotency_key":"expense"}
    with pytest.raises(psycopg.errors.CheckViolation,match="outside run"):
        call(conn,org,run,"propose_obligation_update",{**args,"source_refs":[foreign]})
    for status in ("owner_attested","provider_confirmed","statement_reconciled"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege,match="trusted"):
            call(conn,org,run,"propose_obligation_update",{**args,"source_refs":[ref],"evidence_status":status})
    call(conn,org,run,"record_source",{"external_id":"payable-source","source_type":"test_fixture","version":2,"content_sha256":"b"*64,"idempotency_key":"revised-source"})
    with pytest.raises(psycopg.errors.CheckViolation,match="stale"):
        call(conn,org,run,"propose_obligation_update",{**args,"source_refs":[ref]})
    current={"id":str(conn.execute("select id from source_items where run_id=%s and version=2",(run,)).fetchone()[0]),"version":2}
    assert call(conn,org,run,"propose_obligation_update",{**args,"source_refs":[current]})["version"]==1


def test_owner_attestation_is_authenticated_cas_audited_and_preserved(state):
    conn,org,run,users=state
    obligation=payable(conn,org,run)
    query="select attest_finance_obligation(%s,%s,%s,%s,%s)"
    values=(org,run,obligation,1,"I checked this explicitly labeled test expense")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(query,values)
    conn.execute("reset role")
    conn.execute("update memberships set role='director' where user_id=%s",(users[0],))
    identity(conn,users[0])
    attested=conn.execute(query,values).fetchone()[0]
    assert attested["version"]==2 and attested["evidence_status"]=="owner_attested"
    with pytest.raises(psycopg.errors.SerializationFailure):
        conn.execute(query,values)
    identity(conn,service=True)
    updated=call(conn,org,run,"propose_obligation_update",{"id":obligation,"expected_version":2,"title":"Updated amount",
        "direction":"payable","currency":"USD","amount_minor":"301","source_refs":[source_ref(conn,org,run)],"idempotency_key":"update-attested"})
    # A changed amount is a new assertion, so the old owner's attestation must
    # not be silently carried to it. The wrapper downgrades changed assertions.
    assert updated["version"]==3
    assert conn.execute("select evidence_status from obligations where id=%s",(obligation,)).fetchone()[0]=="reported"
    assert conn.execute("select count(*) from audit_events where run_id=%s and event_type='obligation_owner_attested'",(run,)).fetchone()[0]==1


@pytest.mark.parametrize("operation",["assert_payment_run_authorized","create_approval_request","reserve_approved_payment","transition_payment","confirm_payment"])
def test_public_demo_cannot_reach_payment_capabilities_even_with_service_credentials(state,operation):
    conn,org,run,users=state
    conn.execute("update demo_runs set is_demo=true,owner_user_id=%s where id=%s",(users[0],run))
    with pytest.raises(psycopg.errors.InsufficientPrivilege,match="public demo"):
        call(conn,org,run,operation,{})
    with pytest.raises(psycopg.errors.InsufficientPrivilege,match="public demo"):
        conn.execute("select record_finance_income(%s,%s,'{}','fixture','fixture')",(org,run))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select finance_kernel_call_v8(%s,%s,'list_due_work','{}')",(org,run))


def test_provider_authorization_is_explicit_scoped_private_and_active(state):
    conn,org,run,_=state
    args={"configured_organization_id":str(org),"configured_run_id":str(run),"sender":"0x"+"1"*40}
    assert call(conn,org,run,"assert_payment_run_authorized",args)["authorized"]
    with pytest.raises(psycopg.errors.InsufficientPrivilege,match="not authorized"):
        call(conn,org,run,"assert_payment_run_authorized",{**args,"configured_run_id":str(uuid4())})
    conn.execute("update demo_runs set status='closed' where id=%s",(run,))
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        call(conn,org,run,"assert_payment_run_authorized",args)


def test_attempt_claim_and_holdout_are_durable_nonrenewable_and_bounded(state):
    conn,org,run,_=state
    baseline,_=skill_pair(conn,org,run)
    first=attempt_arguments(conn,org,run,baseline)
    assert call(conn,org,run,"claim_improvement_attempt",first)["claimed"]
    assert call(conn,org,run,"claim_improvement_attempt",{**first,"attempt_id":str(uuid4())})["reason"]=="improvement_attempt_already_claimed"
    holdout={"attempt_id":first["attempt_id"],"suite_id":first["suite_id"],"transfer_fingerprints":["3"*64]}
    assert call(conn,org,run,"claim_improvement_holdout",holdout)["claimed"]
    assert call(conn,org,run,"claim_improvement_holdout",holdout)["reason"]=="transfer_holdout_already_consumed"
    assert call(conn,org,run,"finish_improvement_attempt",{"attempt_id":first["attempt_id"],"status":"rejected","model_calls_used":12,"reason":"No gain"})["reserved_model_calls"]==40
    assert not call(conn,org,run,"claim_improvement_holdout",holdout)["claimed"]
    for _ in range(2):
        other=attempt_arguments(conn,org,run,baseline)
        assert call(conn,org,run,"claim_improvement_attempt",other)["claimed"]
        assert call(conn,org,run,"claim_improvement_holdout",{**holdout,"attempt_id":other["attempt_id"]})["reason"]=="transfer_holdout_already_consumed"
    assert call(conn,org,run,"claim_improvement_attempt",attempt_arguments(conn,org,run,baseline))["reason"]=="run_improvement_attempt_budget_exhausted"
    conn.execute("reset role")
    assert conn.execute("select reserved_model_calls,reserved_improvement_attempts from finance_run_execution_limits where run_id=%s",(run,)).fetchone()==(120,3)


def test_concurrent_public_inference_reservations_cannot_overdraw_and_visitors_cannot_raise_limits(database,state):
    conn,org,run,users=state
    conn.execute("update demo_runs set is_demo=true,owner_user_id=%s where id=%s",(users[0],run))
    conn.execute("reset role")
    conn.execute("update memberships set role='director' where user_id=%s",(users[0],))
    identity(conn,users[0])
    with pytest.raises(psycopg.errors.InsufficientPrivilege,match="visitors"):
        conn.execute("select set_finance_execution_limits(%s,%s,1000,9)",(org,run))
    identity(conn,service=True)
    reservation=str(uuid4())
    assert call(conn,org,run,"reserve_run_inference",{"reservation_id":reservation,"max_model_calls":40})["claimed"]
    assert not call(conn,org,run,"reserve_run_inference",{"reservation_id":reservation,"max_model_calls":40})["claimed"]
    def reserve(_):
        with psycopg.connect(database,autocommit=True) as worker:
            identity(worker,service=True)
            return call(worker,org,run,"reserve_run_inference",{"reservation_id":str(uuid4()),"max_model_calls":40})["claimed"]
    with ThreadPoolExecutor(4) as pool:
        assert sum(pool.map(reserve,range(4)))==2
    conn.execute("reset role")
    assert conn.execute("select model_call_limit,reserved_model_calls from finance_run_execution_limits where run_id=%s",(run,)).fetchone()==(120,120)


def test_private_budget_is_larger_and_only_director_can_raise_without_erasing_usage(state):
    conn,org,run,users=state
    assert call(conn,org,run,"reserve_run_inference",{"reservation_id":str(uuid4()),"max_model_calls":9})["claimed"]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select set_finance_execution_limits(%s,%s,2000,5)",(org,run))
    conn.execute("reset role")
    assert conn.execute("select model_call_limit from finance_run_execution_limits where run_id=%s",(run,)).fetchone()[0]==1000
    conn.execute("update memberships set role='director' where user_id=%s",(users[0],))
    identity(conn,users[0])
    changed=conn.execute("select set_finance_execution_limits(%s,%s,2000,5)",(org,run)).fetchone()[0]
    assert changed["model_call_limit"]==2000 and changed["reserved_model_calls"]==9
    with pytest.raises(psycopg.errors.CheckViolation,match="erase"):
        conn.execute("select set_finance_execution_limits(%s,%s,8,5)",(org,run))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("update finance_run_execution_limits set reserved_model_calls=0 where run_id=%s",(run,))


def test_competing_attempt_and_holdout_claims_are_atomic(database,state):
    conn,org,run,_=state
    baseline,_=skill_pair(conn,org,run)
    args=attempt_arguments(conn,org,run,baseline)
    def claim(arguments):
        with psycopg.connect(database,autocommit=True) as worker:
            identity(worker,service=True)
            return call(worker,org,run,"claim_improvement_attempt",arguments)
    with ThreadPoolExecutor(2) as pool:
        outcomes=list(pool.map(claim,[args,{**args,"attempt_id":str(uuid4())}]))
    assert sum(item["claimed"] for item in outcomes)==1
    first=next(item for item in outcomes if item["claimed"])
    second=attempt_arguments(conn,org,run,baseline)
    assert claim(second)["claimed"]
    def holdout(aid):
        with psycopg.connect(database,autocommit=True) as worker:
            identity(worker,service=True)
            return call(worker,org,run,"claim_improvement_holdout",{"attempt_id":aid,"suite_id":args["suite_id"],"transfer_fingerprints":["3"*64]})
    with ThreadPoolExecutor(2) as pool:
        claims=list(pool.map(holdout,[first["attempt_id"],second["attempt_id"]]))
    assert sum(item["claimed"] for item in claims)==1
    assert next(item for item in claims if not item["claimed"])["reason"]=="transfer_holdout_already_consumed"


@pytest.mark.parametrize("mutation",["missing_pair","transfer_failed","regression_failed","baseline_loss","no_gain","wrong_hash","wrong_manifest","unclaimed_transfer","missing_case"])
def test_sql_promotion_independently_rejects_forged_gate_flags(state,mutation):
    conn,org,run,_=state
    baseline,candidate=skill_pair(conn,org,run)
    evaluation,args=successful_evaluation(conn,org,run,baseline,candidate)
    conn.execute("reset role")
    if mutation=="missing_pair":
        conn.execute("delete from eval_results where eval_run_id=%s and case_key='validation' and variant='baseline'",(evaluation["id"],))
    elif mutation in {"transfer_failed","regression_failed","baseline_loss"}:
        group={"transfer_failed":"transfer","regression_failed":"regression","baseline_loss":"validation"}[mutation]
        conn.execute("update eval_results set passed=false where eval_run_id=%s and case_key=%s and variant='candidate'",(evaluation["id"],group))
    elif mutation=="no_gain":
        conn.execute("update eval_results set metrics='{\"tool_calls\":2}' where eval_run_id=%s",(evaluation["id"],))
    elif mutation=="wrong_hash":
        conn.execute("update eval_results set details=jsonb_set(details,'{source_snapshot_hash}',%s) where eval_run_id=%s and case_key='transfer' and variant='candidate'",(Jsonb("4"*64),evaluation["id"]))
    elif mutation=="wrong_manifest":
        conn.execute("update eval_runs set metrics=jsonb_set(metrics,'{suite_manifest_sha256}',%s) where id=%s",(Jsonb("5"*64),evaluation["id"]))
    elif mutation=="unclaimed_transfer":
        conn.execute("delete from finance_improvement_holdouts where attempt_id=%s",(args["attempt_id"],))
    else:
        conn.execute("delete from eval_results where eval_run_id=%s and case_key='validation'",(evaluation["id"],))
    identity(conn,service=True)
    with pytest.raises(psycopg.errors.CheckViolation,match="gate"):
        activate(conn,org,run,baseline,candidate,evaluation)
    assert call(conn,org,run,"get_active_skill",{"skill_name":"organizer-expenses"})["id"]==baseline["id"]


def test_complete_protected_sql_gate_promotes_then_replay_does_not_promote_twice(state):
    conn,org,run,_=state
    baseline,candidate=skill_pair(conn,org,run)
    evaluation,_=successful_evaluation(conn,org,run,baseline,candidate)
    first=activate(conn,org,run,baseline,candidate,evaluation)
    assert activate(conn,org,run,baseline,candidate,evaluation)==first
    assert conn.execute("select count(*) from promotions where run_id=%s and state='promoted'",(run,)).fetchone()[0]==1


@pytest.mark.asyncio
async def test_python_actor_cannot_assert_confirmation_or_use_prepare_only_provider():
    class NoNetwork:
        async def rpc(self,*args,**kwargs):
            raise AssertionError("must reject before network")
    scope=Scope(uuid4(),uuid4())
    tools=FinanceToolClient(scope,NoNetwork())
    with pytest.raises(FinanceError,match="trusted"):
        await tools.call("propose_obligation_update",{"evidence_status":"provider_confirmed"})
    with pytest.raises(PaymentError,match="explicit"):
        await assert_payment_run_authorized(tools,Settings(_env_file=None))
    with pytest.raises(PaymentError,match="not_authorized"):
        await assert_payment_run_authorized(tools,Settings(_env_file=None,organization_id=uuid4(),run_id=uuid4(),coinbase_sender_address="0x"+"1"*40))
    with pytest.raises(PaymentError,match="evaluation"):
        await assert_payment_run_authorized(FinanceToolClient(scope,NoNetwork(),prepare_only=True),Settings(_env_file=None))

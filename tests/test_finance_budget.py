"""Budget/coordination contracts on actual isolated PostgreSQL, no providers."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_finance_postgres import approve, call, identity, opening, payable, source_ref
from test_finance_postgres import (
    database as database,  # noqa: PLC0414 -- pytest fixture registration
)
from test_finance_postgres import (
    state as state,  # noqa: PLC0414 -- pytest fixture registration
)

from app.finance.tools import FinanceToolClient
from app.finance.types import FinanceError, Scope


def make_director(conn,org,user):
    conn.execute("reset role")
    conn.execute("update memberships set role='director' where organization_id=%s and user_id=%s",(org,user))
    identity(conn,user)


def propose(conn,org,run,**changes):
    payload={"new_name":"Food","allocated_minor":"1000","rationale":"Test event allocation","idempotency_key":"budget-test-key",**changes}
    return conn.execute("select propose_finance_budget(%s,%s,%s)",(org,run,Jsonb(payload))).fetchone()[0]


def decide(conn,org,run,decision,value="approve"):
    return conn.execute("select decide_finance_budget(%s,%s,%s,%s)",(org,run,decision["id"],value)).fetchone()[0]


def configure(conn,org,run,user,amount="1000",key="budget-test-key"):
    make_director(conn,org,user)
    decision=propose(conn,org,run,allocated_minor=amount,idempotency_key=key)
    assert decide(conn,org,run,decision)["status"]=="approved"
    identity(conn,service=True)
    return decision["budget_line_id"]


def expense(conn,org,run,line,amount="300",key="expense-test"):
    return call(conn,org,run,"propose_obligation_update",{"title":"Source-backed fixture expense","direction":"payable","currency":"USD",
        "amount_minor":amount,"budget_line_id":line,"source_refs":[source_ref(conn,org,run,key+"-source")],"idempotency_key":key})


def payment_proposal(conn,org,run,obligation,key="payment-test"):
    current=next(item for item in call(conn,org,run,"get_obligations",{}) if item["id"]==obligation["id"])
    return call(conn,org,run,"create_approval_request",{"action":{"type":"payment","amount_minor":current["amount_minor"],"currency":"USD",
        "asset":"USDC","network":"base-sepolia","destination":"fixture-recipient","obligation_id":current["id"],"obligation_version":current["version"]},"idempotency_key":key})


def test_budget_requires_director_decision_and_exact_idempotent_request(state):
    conn,org,run,users=state
    proposed=propose(conn,org,run)
    assert conn.execute("select count(*) from budget_lines where run_id=%s",(run,)).fetchone()[0]==0
    identity(conn,users[0])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        decide(conn,org,run,proposed)
    make_director(conn,org,users[0])
    identity(conn,users[0],service=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        decide(conn,org,run,proposed)
    identity(conn,users[0])
    result=decide(conn,org,run,proposed)
    assert result["status"]=="approved" and result["decided_by"]==str(users[0])
    assert decide(conn,org,run,proposed)==result
    assert propose(conn,org,run)==result
    with pytest.raises(psycopg.errors.UniqueViolation,match="idempotency"):
        propose(conn,org,run,allocated_minor="1001")
    with pytest.raises(psycopg.errors.UniqueViolation,match="idempotency"):
        propose(conn,org,run,new_name="Different exact request")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("update budget_decisions set status='approved' where id=%s",(proposed["id"],))


@pytest.mark.parametrize("change",[{"new_name":None},{"rationale":"  "},{"allocated_minor":None},{"allocated_minor":"9000000000000000001"},
    {"new_name":4},{"idempotency_key":None},{"budget_line_id":None},{"new_name":""},{"unexpected":"policy"}])
def test_budget_nulls_wrong_types_unknown_fields_and_invalid_amounts_fail_before_write(state,change):
    conn,org,run,_=state
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        propose(conn,org,run,**change)
    assert conn.execute("select count(*) from budget_decisions where run_id=%s",(run,)).fetchone()[0]==0


def test_budget_rejection_has_no_effect_and_cannot_later_be_approved(state):
    conn,org,run,users=state
    make_director(conn,org,users[0])
    decision=propose(conn,org,run)
    assert decide(conn,org,run,decision,"reject")["status"]=="rejected"
    assert decide(conn,org,run,decision,"reject")["status"]=="rejected"
    with pytest.raises(psycopg.errors.SerializationFailure):
        decide(conn,org,run,decision)
    assert conn.execute("select count(*) from budget_lines where run_id=%s",(run,)).fetchone()[0]==0


def test_budget_version_revision_cross_scope_and_inflight_payment_guards(state):
    conn,org,run,users=state
    opening(conn,org,run)
    line=configure(conn,org,run,users[0])
    obligation=expense(conn,org,run,line)
    make_director(conn,org,users[0])
    decision=propose(conn,org,run,budget_line_id=line,expected_version=1,allocated_minor="1200",idempotency_key="budget-increase")
    identity(conn,service=True)
    source_ref(conn,org,run,"new-material-evidence")
    identity(conn,users[0])
    with pytest.raises(psycopg.errors.SerializationFailure,match="event changed"):
        decide(conn,org,run,decision)
    assert conn.execute("select get_finance_budget(%s,%s)",(org,run)).fetchone()[0]["decisions"][0]["status"]=="stale"
    with pytest.raises(psycopg.errors.SerializationFailure,match="version"):
        propose(conn,org,run,budget_line_id=line,expected_version=999,idempotency_key="wrong-version")
    identity(conn,service=True)
    p=payment_proposal(conn,org,run,obligation)
    approve(conn,users[1],p);approve(conn,users[2],p)
    identity(conn,service=True)
    call(conn,org,run,"reserve_approved_payment",{"proposal_id":p["id"],"idempotency_key":"reserved-test"})
    identity(conn,users[0])
    pending=propose(conn,org,run,budget_line_id=line,expected_version=1,idempotency_key="pending-payment")
    with pytest.raises(psycopg.errors.SerializationFailure,match="payment in progress"):
        decide(conn,org,run,pending)
    identity(conn,users[3])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        decide(conn,org,run,pending)
    identity(conn,service=True)
    other=uuid4()
    conn.execute("insert into demo_runs(id,organization_id,name) values(%s,%s,'Other budget run')",(other,org))
    with pytest.raises(psycopg.errors.NoDataFound):
        propose(conn,org,other,budget_line_id=line,expected_version=1)


def test_budget_totals_include_settled_spend_and_allocation_cannot_erase_commitments(state):
    conn,org,run,users=state
    line=configure(conn,org,run,users[0])
    first=expense(conn,org,run,line,"300")
    expense(conn,org,run,line,"200",key="second-expense")
    conn.execute("update obligations set settled_minor=300,status='settled' where id=%s",(first["id"],))
    identity(conn,users[0])
    budget=conn.execute("select get_finance_budget(%s,%s)",(org,run)).fetchone()[0]
    assert budget["lines"][0]["committed_minor"]=="500" and budget["lines"][0]["remaining_minor"]=="500"
    small=propose(conn,org,run,budget_line_id=line,expected_version=1,allocated_minor="499",idempotency_key="too-small-budget")
    with pytest.raises(psycopg.errors.InvalidParameterValue,match="commitments"):
        decide(conn,org,run,small)


@pytest.mark.parametrize("defect",["unassigned","overcommit"])
def test_configured_budget_blocks_payment_preparation_reservation_and_send_claim(state,defect):
    conn,org,run,users=state
    opening(conn,org,run)
    line=configure(conn,org,run,users[0])
    first=expense(conn,org,run,line)
    p=payment_proposal(conn,org,run,first)
    approve(conn,users[1],p);approve(conn,users[2],p)
    identity(conn,service=True)
    payment=call(conn,org,run,"reserve_approved_payment",{"proposal_id":p["id"],"idempotency_key":"pre-defect-reserve"})
    expense(conn,org,run,None if defect=="unassigned" else line,"900",key="new-expense")
    expected="assign every payable" if defect=="unassigned" else "exceed approved allocation"
    with pytest.raises(psycopg.errors.CheckViolation,match=expected):
        payment_proposal(conn,org,run,first,key="post-defect-proposal")
    with pytest.raises(psycopg.errors.CheckViolation,match=expected):
        call(conn,org,run,"reserve_approved_payment",{"proposal_id":p["id"],"idempotency_key":"pre-defect-reserve"})
    with pytest.raises(psycopg.errors.CheckViolation,match=expected):
        call(conn,org,run,"transition_payment",{"payment_id":payment["id"],"status":"submitting","idempotency_key":"blocked-send"})
    assert call(conn,org,run,"get_payment_status",{"payment_id":payment["id"]})["status"]=="reserved"


def test_unconfigured_budget_preserves_existing_payment_workflow_and_assignments_update_atomically(state):
    conn,org,run,users=state
    obligation={"id":payable(conn,org,run)}
    assert payment_proposal(conn,org,run,obligation)["status"]=="pending"
    line=configure(conn,org,run,users[0])
    current=next(item for item in call(conn,org,run,"get_obligations",{}) if item["id"]==obligation["id"])
    update={"id":current["id"],"expected_version":current["version"],"title":current["title"],"direction":"payable","amount_minor":current["amount_minor"],
        "currency":"USD","budget_line_id":line,"source_refs":current["source_refs"],"idempotency_key":"assign-budget"}
    result=call(conn,org,run,"propose_obligation_update",update)
    assert result["version"]==2
    assigned=next(item for item in call(conn,org,run,"get_obligations",{}) if item["id"]==current["id"])
    assert assigned["budget_line_id"]==line
    assert payment_proposal(conn,org,run,obligation,key="assigned-payment")["status"]=="pending"
    with pytest.raises(psycopg.errors.CheckViolation,match="outside event"):
        call(conn,org,run,"propose_obligation_update",{**update,"budget_line_id":str(uuid4()),"idempotency_key":"foreign-budget"})


def test_obligation_budget_links_reject_real_foreign_run_and_wrong_currency_lines(state):
    conn,org,run,users=state
    other=uuid4()
    conn.execute("insert into demo_runs(id,organization_id,name) values(%s,%s,'Foreign budget')",(other,org))
    foreign_line=configure(conn,org,other,users[0])
    with pytest.raises(psycopg.errors.CheckViolation,match="outside event"):
        expense(conn,org,run,foreign_line)
    wrong=uuid4()
    conn.execute("insert into budget_lines(id,organization_id,run_id,name,currency,allocated_minor) values(%s,%s,%s,'Wrong currency','CAD',1000)",(wrong,org,run))
    with pytest.raises(psycopg.errors.CheckViolation,match="currency"):
        expense(conn,org,run,str(wrong),key="wrong-currency")


def test_competing_budget_decisions_serialize_under_event_revision(database,state):
    conn,org,run,users=state
    make_director(conn,org,users[0])
    decisions=[propose(conn,org,run,new_name=name,idempotency_key="allocate-"+name) for name in ("Food","Venue")]
    def choose(item):
        with psycopg.connect(database,autocommit=True) as worker:
            identity(worker,users[0])
            try:
                return decide(worker,org,run,item)["status"]
            except psycopg.errors.SerializationFailure:
                return "stale"
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(choose,decisions))==["approved","stale"]


@pytest.mark.parametrize("payload",[None,{},[],{"message":None},{"message":4},{"message":"  "},{"message":"x","source_id":str(uuid4())},
    {"message":"x","case_id":None},{"message":"x","case_id":"wrong"},{"message":"x"*4001}])
def test_director_message_input_is_strict_before_enqueuing(state,payload):
    conn,org,run,users=state
    identity(conn,users[0])
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        conn.execute("select enqueue_finance_command(%s,%s,'director_message',%s,'message-key')",(org,run,Jsonb(payload)))
    conn.execute("reset role")
    assert conn.execute("select count(*) from jobs where run_id=%s",(run,)).fetchone()[0]==0


def test_director_message_original_envelope_survives_trusted_payload_enrichment(state):
    conn,org,run,users=state
    identity(conn,users[0])
    query="select enqueue_finance_command(%s,%s,'director_message',%s,'message-key')"
    payload={"message":"Plan the event budget using current recorded evidence."}
    job=conn.execute(query,(org,run,Jsonb(payload))).fetchone()[0]
    identity(conn,service=True)
    conn.execute("update jobs set payload=payload||%s where id=%s",(Jsonb({"case_id":str(uuid4()),"source_id":str(uuid4())}),job))
    identity(conn,users[0])
    assert conn.execute(query,(org,run,Jsonb(payload))).fetchone()[0]==job
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(query,(org,run,Jsonb({"message":"Changed instruction"})))
    identity(conn,users[1])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(query,(org,run,Jsonb(payload)))


def test_director_message_case_binding_and_review_persistence_keep_exact_trace_guards(state):
    conn,org,run,users=state
    ref=source_ref(conn,org,run)
    case=call(conn,org,run,"record_case",{"title":"Director request","data":{"source_ids":[ref["id"]]},"idempotency_key":"message-case"})
    identity(conn,users[0])
    payload={"message":"Review this case","case_id":case["id"]}
    job=conn.execute("select enqueue_finance_command(%s,%s,'director_message',%s,'bound-message')",(org,run,Jsonb(payload))).fetchone()[0]
    identity(conn,service=True)
    output={"decision":"investigate","evidence_source_ids":[ref["id"]],"clarification":"Who paid?","proposed_action":None,"explanation":"Payer evidence missing.","blocking_requirements":[]}
    trace=call(conn,org,run,"record_trace",{"event_type":"actor_completed","payload":{"job_id":str(job),"skill_version":str(uuid4()),"output":output},"idempotency_key":"message-trace"})
    statement="select record_finance_case_review(%s,%s,%s,1,%s,%s,%s,%s,%s)"
    values=(org,run,case["id"],[ref["id"]],trace["id"],job,Jsonb(output),"case-review:"+str(job))
    assert conn.execute(statement,values).fetchone()[0]["status"]=="persisted"
    assert conn.execute(statement,values).fetchone()[0]["status"]=="persisted"
    identity(conn,users[0])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select enqueue_finance_command(%s,%s,'director_message',%s,'unscoped-message')",(org,run,Jsonb({"message":"Review","case_id":str(uuid4())})))


@pytest.mark.parametrize("path_kind",["valid","other_run","artifacts","traversal","viewer","inactive_run"])
def test_authenticated_original_upload_policy_is_scoped_to_active_upload_prefix(state,path_kind):
    conn,org,run,users=state
    conn.execute("reset role")
    conn.execute("grant usage on schema storage to authenticated")
    conn.execute("grant insert,select on storage.objects to authenticated")
    path=f"{org}/{run}/uploads/fixture.pdf"
    if path_kind=="other_run": path=f"{org}/{uuid4()}/uploads/fixture.pdf"
    elif path_kind=="artifacts": path=f"{org}/{run}/artifacts/fixture.pdf"
    elif path_kind=="traversal": path=f"{org}/{run}/uploads/../fixture.pdf"
    elif path_kind=="inactive_run": conn.execute("update demo_runs set status='closed' where id=%s",(run,))
    elif path_kind=="viewer": conn.execute("update memberships set role='viewer' where user_id=%s",(users[0],))
    identity(conn,users[0])
    command="insert into storage.objects(id,name,bucket_id) values(%s,%s,'finance-artifacts')"
    if path_kind=="valid":
        conn.execute(command,(uuid4(),path))
        assert conn.execute("select name from storage.objects where name=%s",(path,)).fetchone()[0]==path
    else:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(command,(uuid4(),path))


@pytest.mark.asyncio
async def test_evaluation_budget_reads_only_frozen_snapshot():
    class NoNetwork:
        async def rpc(self,*args,**kwargs):
            raise AssertionError("evaluation cannot read current budget")
    scope=Scope(uuid4(),uuid4())
    captured={"organization":{"id":str(scope.organization_id)},"run":{"id":str(scope.run_id)},"budget":{"lines":[{"id":"fixture","allocated_minor":"100"}],"decisions":[]}}
    tools=FinanceToolClient(scope,NoNetwork()).for_evaluation(captured)
    captured["budget"]["lines"][0]["allocated_minor"]="999"
    assert (await tools.call("get_budget_plan",{}))["lines"][0]["allocated_minor"]=="100"
    missing={"organization":captured["organization"],"run":captured["run"]}
    with pytest.raises(FinanceError,match="lacks budget"):
        await FinanceToolClient(scope,NoNetwork()).for_evaluation(missing).call("get_budget_plan",{})

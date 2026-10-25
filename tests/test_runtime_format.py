"""No provider calls: actor framing and private diagnostics with a fake process."""

import copy
import hashlib
import json

import pytest

from app.models.providers import ModelConfig, ModelError
from app.runtime import hermes

DECISION={"decision":"investigate","evidence_source_ids":["source-fixture"],"clarification":"Who paid?",
    "proposed_action":None,"explanation":"Payer evidence is missing.","blocking_requirements":[{
        "stage":"obligation_recording","requirement":"payer_identity","supporting_refs":[{"kind":"source","id":"source-fixture","version":1}]}]}


class FakeStdin:
    def __init__(self): self.writes=[]
    def write(self,data): self.writes.append(json.loads(data))
    async def drain(self): pass


class FakeStdout:
    def __init__(self,lines): self.lines=list(lines)
    async def readline(self):
        return (json.dumps(self.lines.pop(0))+"\n").encode() if self.lines else b""


class FakeProcess:
    def __init__(self,lines):
        self.stdin=FakeStdin();self.stdout=FakeStdout(lines);self.returncode=None;self.kills=0
    def kill(self): self.kills+=1;self.returncode=-9
    async def wait(self): self.returncode=0


async def run_fixture(monkeypatch,raw,*,calls=2,metadata=None,limit=8,tools_called=False,command=None):
    lines=[]
    if tools_called:
        lines.append({"type":"tool_call","name":"record_finding","arguments":{"case_id":"case-fixture","expected_version":1,"finding":"Fixture observation","idempotency_key":"fixture-finding"}})
    result={"final_response":raw,"api_calls":calls,"completed":True,"failed":False,"partial":False,**(metadata or {})}
    lines.append({"type":"result","result":result,"usage":{"session_input_tokens":120,"session_output_tokens":100},"provider_request_ids":["fixture-provider-id"]})
    process=FakeProcess(lines)
    monkeypatch.setattr(hermes,"verify_source",lambda source:None)
    async def spawn(*args,**kwargs): return process
    monkeypatch.setattr(hermes.asyncio,"create_subprocess_exec",spawn)
    tool_events=[]
    class Tools:
        async def call(self,name,args):
            tool_events.append((name,copy.deepcopy(args)))
            return {"case_id":"case-fixture","version":2}
    actor=hermes.HermesActor(ModelConfig("fixture-model","https://fixture.invalid/v1","fixture-api-secret"))
    prompt = {"question":"Fixture only", **({"command_type": command} if command else {})}
    return await actor.run(prompt,"Unchanged fixture procedure",Tools(),max_model_calls=limit),process,tool_events


@pytest.mark.asyncio
async def test_valid_json_uses_only_original_calls_and_has_no_recovery_diagnostic(monkeypatch):
    result,process,events=await run_fixture(monkeypatch,json.dumps(DECISION),tools_called=True)
    assert result["output"]==DECISION and result["evidence"]["api_calls"]==2
    assert "format_recovery" not in result["evidence"] and "private_diagnostic" not in result
    assert len(events)==1 and process.kills==1
    assert process.stdin.writes[0]["max_iterations"]==8


@pytest.mark.asyncio
@pytest.mark.parametrize("method",["embedded","literal","trailing"])
async def test_only_complete_existing_content_is_normalized_without_extra_inference_or_tool_replay(monkeypatch,method):
    if method=="embedded": raw="The result follows:\n"+json.dumps(DECISION)+"\nRecommendation only."
    elif method=="literal": raw=repr(DECISION)
    else: raw=json.dumps(DECISION)[:-1]+",}"
    before=raw
    result,process,events=await run_fixture(monkeypatch,raw,calls=8,tools_called=True)
    assert result["output"]==DECISION and result["evidence"]["api_calls"]==8
    recovery=result["evidence"]["format_recovery"]
    assert recovery["additional_model_calls"]==0 and recovery["status"]=="normalized_existing_content"
    assert recovery["original_response_sha256"]==hashlib.sha256(raw.encode()).hexdigest()
    diagnostic=result["private_diagnostic"]
    assert diagnostic["original_final_response"]==before and diagnostic["api_calls"]==8
    assert diagnostic["provider_usage"]=={"session_input_tokens":120,"session_output_tokens":100}
    assert diagnostic["provider_request_ids"]==["fixture-provider-id"]
    assert len(events)==len(result["tool_events"])==len(diagnostic["tool_events"])==1
    assert len(process.stdin.writes)==2  # initial request + the original tool result
    assert result["evidence"]["usage"]==diagnostic["provider_usage"]


@pytest.mark.asyncio
@pytest.mark.parametrize("calls",[None,True,"2",2.0,-1,9])
async def test_invalid_or_over_budget_actual_call_counts_block_without_additional_calls(monkeypatch,calls):
    raw="Private fixture response: "+json.dumps(DECISION)
    with pytest.raises(hermes.HermesActorError,match="invalid_api_call_count") as failure:
        await run_fixture(monkeypatch,raw,calls=calls,tools_called=True)
    diagnostic=failure.value.private_diagnostic
    assert diagnostic["original_final_response"]==raw and diagnostic["api_calls"]==calls
    assert len(diagnostic["tool_events"])==1 and diagnostic["format_recovery"]["additional_model_calls"]==0
    assert raw not in str(failure.value) and raw not in repr(failure.value)
    diagnostic["original_final_response"]="changed by caller"
    assert failure.value.private_diagnostic["original_final_response"]==raw


@pytest.mark.asyncio
@pytest.mark.parametrize("raw",[
    json.dumps(DECISION)+"\n"+json.dumps(DECISION),
    "```json\n"+json.dumps(DECISION)+"\n```\n"+json.dumps(DECISION),
    '{"decision":"investigate","decision":"no_action"}',
    "{'decision':'investigate','decision':'no_action'}",
])
async def test_multiple_objects_or_duplicate_keys_are_ambiguous_and_never_repaired(monkeypatch,raw):
    with pytest.raises(hermes.HermesActorError) as failure:
        await run_fixture(monkeypatch,raw)
    assert failure.value.code in {"model_output_multiple_json_objects","model_output_ambiguous_json"}
    assert failure.value.private_diagnostic["original_final_response"]==raw
    assert failure.value.private_diagnostic["format_recovery"]["additional_model_calls"]==0


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata",[{"finish_reason":"length"},{"stop_reason":"max_tokens"},{"truncated":True},
    {"turn_exit_reason":"text_response(finish_reason=length)"},{"partial":True},{"completed":False}])
async def test_explicit_truncation_or_incomplete_outcome_preserves_diagnostic_and_blocks(monkeypatch,metadata):
    raw=json.dumps(DECISION)
    with pytest.raises(hermes.HermesActorError) as failure:
        await run_fixture(monkeypatch,raw,metadata=metadata)
    assert failure.value.code in {"hermes_truncated_output","hermes_incomplete_outcome"}
    assert failure.value.private_diagnostic["original_final_response"]==raw


@pytest.mark.asyncio
@pytest.mark.parametrize("raw",[
    "I need more financial evidence and cannot supply a structured decision.",
    json.dumps(DECISION)[:-15],
    '[ '+json.dumps(DECISION)+' ]',
    "Result: {'decision':'investigate'}",
    "Result: {'decision':'investigate','evidence_source_ids':(), 'clarification':None,'proposed_action':None,'explanation':'Missing','blocking_requirements':[]}",
])
async def test_unstructured_truncated_wrong_schema_or_coercive_recovery_cannot_invent_content(monkeypatch,raw):
    with pytest.raises(hermes.HermesActorError) as failure:
        await run_fixture(monkeypatch,raw)
    assert failure.value.private_diagnostic["original_final_response"]==raw
    assert failure.value.private_diagnostic["format_recovery"]["additional_model_calls"]==0


def test_recovery_does_not_strip_commas_or_braces_inside_financial_evidence_strings():
    decision=copy.deepcopy(DECISION)
    decision["explanation"]="Vendor note literally contains comma,} and braces {retained}."
    raw=json.dumps(decision)[:-1]+",}"
    recovered,method=hermes._actor_output(raw,finance=True)
    assert recovered==decision and method=="complete_json_trailing_comma_normalization"


@pytest.mark.asyncio
async def test_requested_budget_remains_exactly_smaller_grant(monkeypatch):
    result,process,_=await run_fixture(monkeypatch,"Result: "+json.dumps(DECISION),calls=2,limit=2)
    assert process.stdin.writes[0]["max_iterations"]==2 and result["evidence"]["api_calls"]==2
    assert result["evidence"]["format_recovery"]["additional_model_calls"]==0


@pytest.mark.asyncio
async def test_timeout_carries_private_tool_history_without_a_result(monkeypatch):
    import asyncio
    process=FakeProcess([])
    async def slow_read():
        await asyncio.sleep(10)
    process.stdout.readline=slow_read
    monkeypatch.setattr(hermes,"verify_source",lambda source:None)
    async def spawn(*args,**kwargs): return process
    monkeypatch.setattr(hermes.asyncio,"create_subprocess_exec",spawn)
    actor=hermes.HermesActor(ModelConfig("fixture-model","https://fixture.invalid/v1","fixture-api-secret"),timeout_seconds=0.01)
    with pytest.raises(hermes.HermesActorError,match="hermes_timeout") as failure:
        await actor.run({},"Fixture",None)
    assert failure.value.private_diagnostic["original_final_response"] is None and process.kills==1
    assert isinstance(failure.value,ModelError)


@pytest.mark.asyncio
async def test_director_conversation_preserves_actual_answer_without_inventing_financial_fields(monkeypatch):
    raw = 'Cash is unknown. The record contains {"approval": "not supplied"}. We need the opening statement.'
    result, process, called = await run_fixture(monkeypatch, raw, command="director_message", tools_called=True)
    assert result["output"] == {"response_type": "director_response", "message": raw,
                                "evidence_source_ids": [], "consulted_source_refs": []}
    assert result["evidence"]["output_contract"] == "finance-director-response-v1"
    assert "record_finding" not in process.stdin.writes[0]["allowed_tools"]
    assert called == []
    assert result["tool_events"][0]["result"]["status"] == "blocked"
    assert "proposed_action" not in result["output"]
    assert result["evidence"]["api_calls"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,metadata,reason", [(" ", {}, "director_response_missing_or_too_large"),
    ("x" * 16001, {}, "director_response_missing_or_too_large"),
    (" " * 16000 + "x", {}, "director_response_missing_or_too_large"),
    ("An unfinished answer", {"finish_reason": "length"}, "hermes_truncated_output")])
async def test_director_conversation_still_blocks_empty_oversized_and_truncated_answers(monkeypatch,raw,metadata,reason):
    with pytest.raises(hermes.HermesActorError) as failure:
        await run_fixture(monkeypatch, raw, command="director_message", metadata=metadata)
    assert failure.value.code == reason

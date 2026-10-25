import json
from unittest.mock import patch

import httpx
import pytest

from app.models.providers import GenerativeModel, JevClient, ModelConfig, ModelError
from app.runtime.opencode_bridge import FinanceBridge


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['claude-sonnet-5-5','claude-sonnet-4-6'])
async def test_reviewer_preserves_legacy_and_handles_sonnet55(model):
    captured=[]
    def fake_post(url,headers,payload,timeout):
        captured.append(payload)
        return {'model':model,'stop_reason':'end_turn','content':[{'type':'thinking','thinking':'','signature':'fixture-signature'},{'type':'text','text':'{"accepted":true}'}]},'fixture-request'
    config=ModelConfig(model,'https://unit.invalid/v1','fixture-only',api_mode='anthropic_messages')
    with patch('app.models.providers._post',fake_post):
        result=await GenerativeModel(config).complete('Return JSON','fixture')
    assert result['output']=={'accepted':True}
    if model=='claude-sonnet-5-5':
        assert 'temperature' not in captured[0]
        assert captured[0]['thinking']=={'type':'between_tools'}
        assert captured[0]['output_config']=={'effort':'high'}
    else:
        assert captured[0]['temperature']==0
        assert 'thinking' not in captured[0]


@pytest.mark.asyncio
async def test_bridge_normalizes_sonnet55_without_loosening_call_or_token_bounds():
    config=ModelConfig('claude-sonnet-5-5','https://unit.invalid/v1','fixture-only',api_mode='anthropic_messages',max_tokens=1234)
    seen=[]
    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200,json={'id':'fixture','model':config.model,'content':[{'type':'text','text':'{}'}],'usage':{'input_tokens':3,'output_tokens':2}},headers={'request-id':'fixture'})
    bridge=FinanceBridge(config,None,frozenset(),1,structured=True)
    bridge._client._transport=httpx.MockTransport(respond)
    original={'model':config.model,'max_tokens':9999,'temperature':1,'top_p':0.2,'top_k':4,'thinking':{'type':'disabled'},'output_config':{'format':{'type':'json_schema'}},'tools':[{'name':'StructuredOutput'}],'tool_choice':{'type':'tool','name':'StructuredOutput'}}
    try:
        status,_,_=await bridge.provider(original)
        assert status==200
        request=seen[0]
        assert request['max_tokens']==1234
        assert not any(k in request for k in ('temperature','top_p','top_k'))
        assert request['thinking']=={'type':'between_tools'}
        assert request['output_config']=={'format':{'type':'json_schema'},'effort':'high'}
        assert request['tool_choice']=={'type':'auto'}
        assert original['temperature']==1
        assert (await bridge.provider(original))[0]==400
        assert len(seen)==1
    finally:
        await bridge._client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['refusal', 'max_tokens', 'model_context_window_exceeded', 'pause_turn', None])
async def test_sonnet55_reviewer_rejects_incomplete_or_refused_json_without_retry(reason):
    attempts = []
    def respond(*args):
        attempts.append(1)
        return {'content': [{'type': 'text', 'text': '{"accepted":true}'}], 'stop_reason': reason}, 'fixture'
    config = ModelConfig('claude-sonnet-5-5', 'https://unit.invalid/v1', 'fixture-only', api_mode='anthropic_messages')
    with patch('app.models.providers._post', respond), pytest.raises(ModelError) as error:
        await GenerativeModel(config).complete('Return JSON', 'fixture')
    assert error.value.code == ('provider_refusal' if reason == 'refusal' else 'provider_incomplete_response')
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_sonnet55_bridge_preserves_signed_history_and_legacy_config_is_unchanged():
    messages = [{'role': 'user', 'content': 'fixture task'},
                {'role': 'assistant', 'content': [
                    {'type': 'thinking', 'thinking': '', 'signature': 'signed-fixture'},
                    {'type': 'tool_use', 'id': 'fixture-tool', 'name': 'finance_get_case', 'input': {'case_id': 'fixture'}}]},
                {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'fixture-tool', 'content': 'fixture result'}]}]
    for model in ('claude-sonnet-5-5', 'claude-sonnet-4-6'):
        config = ModelConfig(model, 'https://unit.invalid/v1', 'fixture-only', api_mode='anthropic_messages')
        seen = []
        def respond(request, seen=seen, model=model):
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={'model': model, 'content': [], 'stop_reason': 'end_turn'})
        bridge = FinanceBridge(config, None, frozenset({'get_case'}), 1, structured=True)
        bridge._client._transport = httpx.MockTransport(respond)
        try:
            status, _, _ = await bridge.provider({'model': model, 'messages': messages,
                'tools': [{'name': 'finance_get_case'}, {'name': 'StructuredOutput'}],
                'tool_choice': {'type': 'any'}, 'temperature': 1})
            assert status == 200
            assert seen[0]['messages'] == messages
            if model == 'claude-sonnet-5-5':
                assert seen[0]['tool_choice'] == {'type': 'auto'}
                assert seen[0]['thinking'] == {'type': 'between_tools'}
                assert 'temperature' not in seen[0]
            else:
                assert seen[0]['tool_choice'] == {'type': 'any'}
                assert seen[0]['temperature'] == 0
                assert 'thinking' not in seen[0]
        finally:
            await bridge._client.aclose()


def test_jev_remains_the_independent_typesafe_model():
    assert JevClient.model == 'typesafe-ai/jev-1.14.0'
    assert JevClient.endpoint == 'https://ai-gateway.vercel.sh/typesafe/v1/systemone'


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['claude-sonnet-5-5','claude-sonnet-4-6'])
async def test_ocr_payload_and_unverified_output(model):
    from app.documents import ClaudeVisionOCR, DocumentLimits
    seen=[]
    def post(url,headers,payload,timeout):
        seen.append(payload)
        return {'id':'ocr-fixture','model':model,'stop_reason':'end_turn','content':[
            {'type':'thinking','thinking':'','signature':'ocr-fixture-signature'},
            {'type':'text','text':json.dumps({'pages':[{'page':1,'text':'fixture USD 5.00','uncertain':False}]})}],'usage':{}},'fixture'
    config=ModelConfig(model,'https://unit.invalid/v1','fixture-only',api_mode='anthropic_messages')
    with patch('app.documents.ocr._post',post):
        result=await ClaudeVisionOCR(config).extract(b'fixture-image','image/png',{'page_count':1,'pages':[]},DocumentLimits())
    assert result['pages'][0]['requires_human_verification'] is True
    if model=='claude-sonnet-5-5':
        assert 'temperature' not in seen[0]
        assert seen[0]['thinking']=={'type':'between_tools'}
    else:
        assert seen[0]['temperature']==0


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['refusal', 'max_tokens', 'model_context_window_exceeded', 'pause_turn', None])
async def test_sonnet55_ocr_keeps_existing_fail_closed_terminal_guard(reason):
    from app.documents import ClaudeVisionOCR, DocumentLimits

    seen = []
    local = {'status': 'needs_ocr', 'page_count': 1, 'pages': [], 'missing_text_pages': [1]}
    def post(url, headers, payload, timeout):
        seen.append(payload)
        return {'id': 'ocr-refused-fixture', 'model': 'claude-sonnet-5-5', 'stop_reason': reason,
                'content': [{'type': 'text', 'text': json.dumps({'pages': [
                    {'page': 1, 'text': 'Must not be accepted despite valid JSON', 'uncertain': False}
                ]})}], 'usage': {'output_tokens': 20}}, 'fixture'
    config = ModelConfig('claude-sonnet-5-5', 'https://unit.invalid/v1', 'fixture-only',
                         api_mode='anthropic_messages')
    with patch('app.documents.ocr._post', post):
        result = await ClaudeVisionOCR(config).extract(b'fixture-image', 'image/png', local, DocumentLimits())
    assert len(seen) == 1
    assert result['status'] == 'needs_ocr'
    assert result['reason'] == 'ocr_incomplete_response'
    assert result['pages'] == []
    assert result['ocr_failure']['code'] == 'ocr_incomplete_response'
    assert result['ocr_provenance']['usage'] == {'output_tokens': 20}
    assert seen[0]['max_tokens'] == 4096
    assert local['pages'] == []

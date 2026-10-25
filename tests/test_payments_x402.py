"""Official x402 SDK protocol tests using an explicitly fake facilitator."""
import base64
import json

import httpx
import pytest
from fastapi import FastAPI

pytest.importorskip("x402")

from x402.schemas import SettleResponse, SupportedResponse, VerifyResponse

from app.payments.types import NETWORK, USDC_ADDRESS
from app.payments.x402_server import X402Config, create_x402_app

PAY_TO="0x2222222222222222222222222222222222222222"
PAYER="0x1111111111111111111111111111111111111111"
TX="0x"+"a"*64


class TestFacilitator:
    """Test double; it performs no cryptographic validation or settlement."""
    __test__=False
    def __init__(self): self.verifications=0; self.settlements=0
    def get_supported(self):
        return SupportedResponse(kinds=[{"x402Version":2,"scheme":"exact","network":NETWORK}])
    async def verify(self,payload,requirements):
        self.verifications+=1
        return VerifyResponse(isValid=True,payer=PAYER)
    async def settle(self,payload,requirements):
        self.settlements+=1
        return SettleResponse(success=True,payer=PAYER,transaction=TX,network=NETWORK)


class TestRecorder:
    __test__=False
    def __init__(self): self.calls=[]
    async def reconcile(self,**kwargs):
        self.calls.append(kwargs)
        return {"status":"pending_verification"}


async def resource(): return {"title":"Explicit synthetic test report"}


@pytest.mark.asyncio
async def test_unconfigured_receiver_is_503_not_fabricated_payment_challenge():
    app=create_x402_app(X402Config(None),recorder=None,resource_provider=resource)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="https://test.invalid") as client:
        response=await client.get("/sponsor-report")
    assert response.status_code==503


@pytest.mark.asyncio
async def test_official_sdk_challenges_exact_base_sepolia_usdc_then_records_settlement():
    facilitator,recorder=TestFacilitator(),TestRecorder()
    app=create_x402_app(X402Config(PAY_TO),recorder=recorder,resource_provider=resource,facilitator=facilitator)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="https://test.invalid") as client:
        challenge=await client.get("/sponsor-report")
        assert challenge.status_code==402
        required=json.loads(base64.b64decode(challenge.headers["PAYMENT-REQUIRED"]))
        option=required["accepts"][0]
        assert option["network"]==NETWORK and option["amount"]=="10000"
        assert option["asset"].lower()==USDC_ADDRESS.lower() and option["payTo"].lower()==PAY_TO
        assert facilitator.settlements==0 and recorder.calls==[]
        # The fake facilitator accepts this synthetic signature; this is protocol
        # plumbing evidence only, never proof of an actual signed payment.
        payment={"x402Version":2,"accepted":option,"payload":{"signature":"0x"+"0"*130,
            "authorization":{"from":PAYER,"to":PAY_TO,"value":"10000","validAfter":"0","validBefore":"9999999999","nonce":"0x"+"0"*64}}}
        encoded=base64.b64encode(json.dumps(payment).encode()).decode()
        paid=await client.get("/sponsor-report",headers={"PAYMENT-SIGNATURE":encoded})
    assert paid.status_code==200
    assert paid.json()["report"]["title"]=="Explicit synthetic test report"
    assert facilitator.settlements==1 and recorder.calls==[{"tx_hash":TX,"payer":PAYER}]
    assert "PAYMENT-RESPONSE" in paid.headers


@pytest.mark.asyncio
async def test_mounted_endpoint_is_challenged_and_mismatched_prefix_never_leaks_resource():
    for configured_prefix,expected in [("/x402",402),("",402),("/wrong",503)]:
        parent=FastAPI()
        parent.mount("/x402",create_x402_app(X402Config(PAY_TO),recorder=TestRecorder(),
            resource_provider=resource,facilitator=TestFacilitator(),mount_path=configured_prefix))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=parent),base_url="https://test.invalid") as client:
            response=await client.get("/x402/sponsor-report")
        assert response.status_code==expected
        assert "Explicit synthetic test report" not in response.text


@pytest.mark.asyncio
async def test_pending_receipt_queues_durable_delayed_verification_without_credit():
    from uuid import uuid4

    from app.finance.types import Scope
    from app.payments.types import PaymentError
    from app.payments.x402_server import X402SettlementRecorder
    class Tools:
        prepare_only=False
        scope=Scope(uuid4(),uuid4())
        async def call(self,name,args):
            assert name=="record_trace"
            return {"id":"explicit-test-trace"}
    class DB:
        def __init__(self):self.rows=[]
        async def select(self,*args,**kwargs): return self.rows
        async def insert(self,table,values):
            assert table=="jobs";self.rows.append(values)
        async def rpc(self,*args,**kwargs): raise AssertionError("unverified incoming payment must not be credited")
    class PendingVerifier:
        async def verify(self,*args): raise PaymentError("receipt_waiting_for_confirmations")
    db=DB()
    recorder=X402SettlementRecorder(Tools(),db,PendingVerifier(),X402Config(PAY_TO))
    first=await recorder.reconcile(tx_hash=TX,payer=PAYER)
    second=await recorder.reconcile(tx_hash=TX,payer=PAYER)
    assert first["status"]==second["status"]=="pending_verification" and first["retryable"]
    assert len(db.rows)==1 and db.rows[0]["payload"]=={"source":"x402","transaction_hash":TX,"payer":PAYER}


@pytest.mark.asyncio
async def test_public_reconciliation_payload_requires_prior_server_report(monkeypatch):
    from uuid import uuid4

    from app.finance.types import Scope
    from app.payments.x402_server import reconcile_configured_income
    monkeypatch.setenv("X402_PAY_TO_ADDRESS",PAY_TO)
    class Tools:
        scope=Scope(uuid4(),uuid4())
    class DB:
        async def select(self,table,**kwargs):
            assert table=="trace_events"
            return []
    result=await reconcile_configured_income(Tools(),DB(),{"transaction_hash":TX,"payer":PAYER,"pay_to":"arbitrary-injected-recipient"})
    assert result["status"]=="blocked" and result["reason"]=="unrecognized_x402_settlement"


@pytest.mark.asyncio
async def test_configured_http_app_denies_before_paid_middleware_for_unbound_run(monkeypatch):
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from app.config import Settings
    from app.connectors import oauth_api
    from app.payments import authorization
    from app.payments.types import PaymentError

    settings = Settings(_env_file=None, supabase_url="https://unit.invalid", supabase_secret_key="sb_secret_explicit_fixture",
                        organization_id=uuid4(), run_id=uuid4(), coinbase_sender_address=PAY_TO, x402_pay_to_address=PAY_TO)
    monkeypatch.setattr(oauth_api, "Settings", lambda: settings)
    denied = AsyncMock(side_effect=PaymentError("demo_payment_effect_denied"))
    monkeypatch.setattr(authorization, "assert_payment_run_authorized", denied)
    app = oauth_api.create_app()
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://unit.invalid") as client:
        response = await client.get("/x402/sponsor-report")
    assert response.status_code == 503
    assert response.json()["reason"] == "private_event_payment_binding_required"
    assert "PAYMENT-REQUIRED" not in response.headers
    denied.assert_awaited_once()

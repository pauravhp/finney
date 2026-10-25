"""Explicit unit/provider-transport fixtures. These do not settle testnet funds."""
import copy
import json
from uuid import uuid4

import httpx
import pytest

from app.payments.chain import BaseSepoliaVerifier
from app.payments.executor import PaymentExecutor
from app.payments.types import NETWORK, TRANSFER_TOPIC, USDC_ADDRESS, PaymentError, TransferIntent
from app.payments.wallet_mcp import CoinbaseWalletMCP

SENDER = "0x1111111111111111111111111111111111111111"
DESTINATION = "0x2222222222222222222222222222222222222222"
TX = "0x" + "a" * 64
BLOCK = "0x" + "b" * 64


def action():
    return {"type":"payment","amount_minor":"1","amount_base_units":"10000","currency":"USD",
            "asset":"USDC","asset_decimals":6,"token_address":USDC_ADDRESS,"network":NETWORK,
            "sender":SENDER,"destination":DESTINATION}


@pytest.mark.parametrize("change", [
    {"network":"eip155:8453"}, {"asset":"ETH"}, {"amount_base_units":"10001"},
    {"amount_minor":0.01}, {"asset_decimals":18}, {"token_address":"0x"+"3"*40},
    {"sender":"0x"+"4"*40},
])
def test_approved_intent_requires_exact_testnet_conversion(change):
    with pytest.raises((PaymentError,ValueError)):
        TransferIntent.from_action({**action(),**change},expected_sender=SENDER)


def rpc_results():
    return {"eth_chainId":"0x14a34","eth_blockNumber":"0x65",
            "eth_getBlockByNumber":{"hash":BLOCK},"eth_call":"0x06",
            "eth_getTransactionReceipt":{"transactionHash":TX,"status":"0x1","blockNumber":"0x64","blockHash":BLOCK,
            "logs":[{"address":USDC_ADDRESS,"topics":[TRANSFER_TOPIC,"0x"+SENDER[2:].rjust(64,"0"),"0x"+DESTINATION[2:].rjust(64,"0")],
                     "data":hex(10_000),"logIndex":"0x0","transactionHash":TX}]}}


def verifier(results):
    async def handler(request):
        method=json.loads(request.content)["method"]
        return httpx.Response(200,json={"jsonrpc":"2.0","id":1,"result":results[method]})
    return BaseSepoliaVerifier(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_receipt_checks_actual_transfer_and_two_confirmations():
    v=verifier(rpc_results())
    try:
        receipt=await v.verify(TX,TransferIntent.from_action(action(),expected_sender=SENDER))
    finally:
        await v.close()
    assert receipt["amount_base_units"]=="10000" and receipt["amount_minor"]=="1"
    assert receipt["confirmations"]==2 and receipt["log_index"]==0


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation,code", [
    ("chain","wrong_chain"),("amount","exact_usdc"),("asset","exact_usdc"),
    ("sender","exact_usdc"),("failed","failed"),("reorg","canonical"),("pending","pending"),
])
async def test_receipt_rejects_provider_success_without_exact_chain_evidence(mutation,code):
    results=rpc_results()
    if mutation=="chain": results["eth_chainId"]="0x2105"
    elif mutation=="amount": results["eth_getTransactionReceipt"]["logs"][0]["data"]=hex(10001)
    elif mutation=="asset": results["eth_getTransactionReceipt"]["logs"][0]["address"]="0x"+"3"*40
    elif mutation=="sender": results["eth_getTransactionReceipt"]["logs"][0]["topics"][1]="0x"+"3"*64
    elif mutation=="failed": results["eth_getTransactionReceipt"]["status"]="0x0"
    elif mutation=="reorg": results["eth_getBlockByNumber"]["hash"]="0x"+"c"*64
    elif mutation=="pending": results["eth_getTransactionReceipt"]=None
    v=verifier(results)
    try:
        with pytest.raises(PaymentError,match=code):
            await v.verify(TX,TransferIntent.from_action(action(),expected_sender=SENDER))
    finally:
        await v.close()


class TestTools:
    """Explicit test-only durable-state fixture, not a production memory fallback."""
    __test__=False
    prepare_only=False

    def __init__(self,status="reserved",reference=None):
        self.payment={"id":str(uuid4()),"status":status,"provider_reference":reference}
        self.historical_reservation=copy.deepcopy(self.payment)
        self.calls=[]
        self.confirmed=False

    async def call(self,name,args):
        self.calls.append((name,args))
        if name=="get_approval_status": return {"action":action()}
        if name=="reserve_approved_payment": return copy.deepcopy(self.historical_reservation)
        if name=="get_payment_status": return copy.deepcopy(self.payment)
        if name=="transition_payment":
            self.payment["status"]=args["status"]
            self.payment["provider_reference"]=args.get("provider_reference",self.payment["provider_reference"])
            return copy.deepcopy(self.payment)
        if name=="confirm_payment":
            self.confirmed=True; self.payment["status"]="confirmed"
            return {"status":"confirmed"}
        raise AssertionError(name)


class TestWallet:
    __test__=False
    configured=True
    def __init__(self,response=None,error=None): self.response=response; self.error=error; self.sends=0; self.polls=0
    async def verify_sender(self,sender): return None
    async def send(self,intent):
        self.sends+=1
        if self.error: raise self.error
        return self.response
    async def request_status(self,request_id):
        self.polls+=1
        return self.response


class TestVerifier:
    __test__=False
    async def network_status(self): return {"network":NETWORK}
    async def verify(self,tx,intent): return {"provider_reference":tx,"status":"confirmed"}


@pytest.mark.asyncio
async def test_wallet_timeout_is_uncertain_and_retry_does_not_send_again():
    tools=TestTools()
    wallet=TestWallet(error=httpx.ReadTimeout("test-only timeout"))
    executor=PaymentExecutor(tools,wallet,TestVerifier(),sender_address=SENDER)
    first=await executor.execute(uuid4())
    second=await executor.execute(uuid4())
    assert first["status"]==second["status"]=="blocked" and wallet.sends==1
    assert tools.payment["status"]=="uncertain" and not tools.confirmed


@pytest.mark.asyncio
async def test_wallet_approval_resume_polls_then_confirms_without_second_send():
    tools=TestTools()
    wallet=TestWallet(response={"requestId":"request-1","approvalUrl":"https://keys.coinbase.com/approve/test-only"})
    executor=PaymentExecutor(tools,wallet,TestVerifier(),sender_address=SENDER)
    proposal=uuid4()
    first=await executor.execute(proposal)
    assert first["reason"]=="awaiting_coinbase_wallet_approval" and not tools.confirmed
    wallet.response={"status":"completed","transactionHash":TX}
    second=await executor.execute(proposal)
    assert second["status"]=="completed" and wallet.sends==1 and wallet.polls==1 and tools.confirmed
    third=await executor.execute(proposal)
    assert third["duplicate"] is True and wallet.sends==1


@pytest.mark.asyncio
async def test_unconfigured_wallet_never_reserves_or_sends():
    tools=TestTools()
    wallet=CoinbaseWalletMCP(None)
    outcome=await PaymentExecutor(tools,wallet,TestVerifier(),sender_address=None).execute(uuid4())
    assert outcome["status"]=="blocked" and tools.calls==[]
    with pytest.raises(PaymentError,match="oauth"):
        await wallet.call("send",{"recipient":DESTINATION,"amount":"0.01","asset":"USDC","chain":"base-sepolia"})


@pytest.mark.asyncio
async def test_wallet_sender_ambiguity_is_rejected_before_remote_send():
    class WalletFixture(CoinbaseWalletMCP):
        def __init__(self,addresses): super().__init__("explicit-test-only-token"); self.addresses=addresses; self.sent=False
        async def call(self,name,arguments):
            if name=="get_wallets": return {"wallets":[{"address":a} for a in self.addresses]}
            self.sent=True
            return {"requestId":"request"}
    intent=TransferIntent.from_action(action(),expected_sender=SENDER)
    for addresses in [[DESTINATION],[SENDER,DESTINATION],[]]:
        wallet=WalletFixture(addresses)
        with pytest.raises(PaymentError,match="ambiguous"):
            await wallet.send(intent)
        assert not wallet.sent
    wallet=WalletFixture([SENDER])
    await wallet.send(intent)
    assert wallet.sent


@pytest.mark.asyncio
async def test_remote_wallet_boundary_denies_mainnet_and_unrestricted_payment_tools():
    wallet=CoinbaseWalletMCP("explicit-test-only-token")
    for tool in ["initiate_x402_request","complete_x402_request","send_calls","sign","swap"]:
        with pytest.raises(PaymentError,match="allowlist"):
            await wallet.call(tool,{})
    with pytest.raises(PaymentError,match="testnet_usdc"):
        await wallet.call("send",{"recipient":DESTINATION,"amount":"0.01","asset":"USDC","chain":"base"})

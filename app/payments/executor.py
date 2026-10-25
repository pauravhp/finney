from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from app.finance.tools import FinanceToolClient
from app.payments.chain import BaseSepoliaVerifier
from app.payments.types import PaymentError, TransferIntent, transaction_hash
from app.payments.wallet_mcp import CoinbaseWalletMCP


def find_transaction_hash(payload: dict[str, Any]) -> str | None:
    """Response fields differ across wallet operations; unknown shapes fail closed."""
    candidates = []
    for key, value in payload.items():
        if key in {"transactionHash", "transaction_hash", "txHash", "hash"} and isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{64}", value):
            candidates.append(transaction_hash(value))
        elif isinstance(value, dict):
            candidate = find_transaction_hash(value)
            if candidate:
                candidates.append(candidate)
    unique = set(candidates)
    if len(unique) > 1:
        raise PaymentError("ambiguous_wallet_transaction_hashes")
    return next(iter(unique)) if unique else None


class PaymentExecutor:
    def __init__(self, tools: FinanceToolClient, wallet: CoinbaseWalletMCP,
                 verifier: BaseSepoliaVerifier, *, sender_address: str | None,
                 max_base_units: int = 100_000_000):
        if tools.prepare_only:
            raise PaymentError("evaluation_cannot_construct_payment_executor")
        self.tools, self.wallet, self.verifier = tools, wallet, verifier
        self.sender_address, self.max_base_units = sender_address, max_base_units

    async def execute(self, proposal_id: str | UUID) -> dict[str, Any]:
        if not self.wallet.configured or not self.sender_address:
            return {"status": "blocked", "reason": "coinbase_wallet_oauth_and_sender_required"}
        proposal_id = str(UUID(str(proposal_id)))
        proposal = await self.tools.call("get_approval_status", {"proposal_id": proposal_id})
        if not proposal:
            raise PaymentError("proposal_not_found")
        intent = TransferIntent.from_action(proposal["action"], expected_sender=self.sender_address, max_base_units=self.max_base_units)
        await self.wallet.verify_sender(intent.sender)
        # Read-only chain check occurs before consuming/reserving application funds.
        await self.verifier.network_status()
        payment = await self.tools.call("reserve_approved_payment", {"proposal_id": proposal_id, "idempotency_key": f"payment:{proposal_id}:reserve"})
        payment_id = payment["id"]
        # Reservation's idempotency result is historical. Always read the current
        # durable status before deciding whether any remote write is permitted.
        payment = await self.tools.call("get_payment_status", {"payment_id": payment_id})
        if payment["status"] == "confirmed":
            return {"status": "completed", "payment_id": payment_id, "provider_reference": payment.get("provider_reference"), "duplicate": True}
        if payment["status"] == "failed":
            return {"status": "blocked", "reason": "previous_payment_failed_requires_new_review", "payment_id": payment_id}
        if payment["status"] == "reserved":
            # Unique claim key is deliberate: an idempotent replay of a successful
            # claim must never authorize a second remote send from a concurrent job.
            try:
                await self.tools.call("transition_payment", {"payment_id": payment_id, "status": "submitting", "idempotency_key": f"payment:{payment_id}:claim:{uuid4()}"})
            except Exception:  # noqa: BLE001 -- losing a claim must fail closed for every provider/DB failure
                return {"status": "blocked", "reason": "payment_claim_not_acquired_or_uncertain", "payment_id": payment_id}
            try:
                response = await self.wallet.send(intent)
                tx_hash = find_transaction_hash(response)
                if tx_hash:
                    payment = await self.tools.call("transition_payment", {"payment_id": payment_id, "status": "submitted", "provider_reference": tx_hash, "idempotency_key": f"payment:{payment_id}:submitted:{tx_hash}"})
                else:
                    request_id, approval_url = response.get("requestId"), response.get("approvalUrl")
                    if not isinstance(request_id, str) or not request_id or len(request_id) > 256:
                        raise PaymentError("wallet_request_id_missing")
                    payment = await self.tools.call("transition_payment", {"payment_id": payment_id, "status": "uncertain", "provider_reference": "wallet-request:"+request_id, "idempotency_key": f"payment:{payment_id}:request:{request_id}"})
                    if not isinstance(approval_url, str) or urlsplit(approval_url).scheme != "https":
                        raise PaymentError("wallet_approval_url_missing_or_invalid")
                    return {"status": "blocked", "reason": "awaiting_coinbase_wallet_approval", "payment_id": payment_id,
                            "request_id": request_id, "approval_url": approval_url}
            except Exception as exc:  # noqa: BLE001 -- any post-claim failure leaves an uncertain external effect
                # A timeout may occur after the provider created a request. Preserve
                # uncertainty; never release/resend money based on a local exception.
                try:
                    await self.tools.call("transition_payment", {"payment_id": payment_id, "status": "uncertain", "idempotency_key": f"payment:{payment_id}:uncertain"})
                except Exception:  # noqa: BLE001 -- persistence may itself be unavailable; never resend
                    return {"status": "blocked", "reason": "submission_and_persistence_uncertain_do_not_resend", "payment_id": payment_id}
                return {"status": "blocked", "reason": "wallet_submission_requires_investigation", "payment_id": payment_id,
                        "error_code": exc.code if isinstance(exc, PaymentError) else "provider_or_persistence_error"}
        if payment["status"] in {"submitting", "uncertain"}:
            reference = payment.get("provider_reference") or ""
            if not reference.startswith("wallet-request:"):
                return {"status": "blocked", "reason": "uncertain_submission_do_not_resend", "payment_id": payment_id}
            request_id = reference.removeprefix("wallet-request:")
            response = await self.wallet.request_status(request_id)
            tx_hash = find_transaction_hash(response)
            if not tx_hash:
                return {"status": "blocked", "reason": "wallet_request_not_chain_confirmed", "payment_id": payment_id, "request_id": request_id}
            payment = await self.tools.call("transition_payment", {"payment_id": payment_id, "status": "submitted", "provider_reference": tx_hash, "idempotency_key": f"payment:{payment_id}:submitted:{tx_hash}"})
        if payment["status"] != "submitted":
            return {"status": "blocked", "reason": "unsupported_durable_payment_state", "payment_id": payment_id}
        try:
            receipt = await self.verifier.verify(payment["provider_reference"], intent)
        except PaymentError as exc:
            return {"status": "blocked", "reason": exc.code, "payment_id": payment_id, "provider_reference": payment["provider_reference"]}
        await self.tools.call("confirm_payment", {"payment_id": payment_id, "receipt": receipt, "idempotency_key": f"payment:{payment_id}:confirm:{payment['provider_reference']}"})
        return {"status": "completed", "payment_id": payment_id, "provider_reference": payment["provider_reference"], "receipt": receipt}


async def execute_configured_payment(tools: FinanceToolClient, proposal_id: str | UUID, *, settings=None) -> dict[str, Any]:
    """Coordinator dispatch entry; configuration is explicit and missing access blocks."""
    from app.config import Settings
    from app.payments.authorization import assert_payment_run_authorized
    settings = settings if settings is not None else Settings()
    token = settings.coinbase_mcp_token.get_secret_value()
    sender = getattr(settings, "coinbase_sender_address", "")
    if not sender:
        return {"status": "blocked", "reason": "coinbase_wallet_oauth_and_sender_required",
                "next_step": "Connect Coinbase Wallet with finance coinbase-connect, verify its address, and set COINBASE_SENDER_ADDRESS"}
    await assert_payment_run_authorized(tools, settings)
    if not token:
        from app.payments.authorization_connect import CoinbaseAuthorizationError, load_access_token
        try:
            token = await load_access_token(settings)
        except CoinbaseAuthorizationError as error:
            return {"status": "blocked", "reason": error.code}
    if not token:
        return {"status": "blocked", "reason": "coinbase_wallet_oauth_required",
                "next_step": "Run finance coinbase-connect for this private event"}
    wallet = CoinbaseWalletMCP(token, url=settings.coinbase_mcp_url or "https://wallet-mcp.coinbase.com")
    verifier = BaseSepoliaVerifier(getattr(settings, "base_sepolia_rpc_url", "https://sepolia.base.org"))
    try:
        return await PaymentExecutor(tools, wallet, verifier, sender_address=sender,
            max_base_units=getattr(settings, "coinbase_max_test_usdc_base_units", 100_000_000)).execute(proposal_id)
    finally:
        await verifier.close()

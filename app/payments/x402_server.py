from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.finance.tools import FinanceToolClient
from app.payments.chain import BaseSepoliaVerifier
from app.payments.types import (
    BASE_UNITS_PER_CENT,
    NETWORK,
    USDC_ADDRESS,
    PaymentError,
    TransferIntent,
    address,
    transaction_hash,
)
from app.storage.supabase import SupabaseClient, SupabaseError


@dataclass(frozen=True)
class X402Config:
    pay_to_address: str | None
    price_base_units: int = 10_000
    facilitator_url: str = "https://x402.org/facilitator"

    def validate(self) -> None:
        if self.pay_to_address:
            address(self.pay_to_address)
        if isinstance(self.price_base_units, bool) or not isinstance(self.price_base_units, int) or not 0 < self.price_base_units <= 100_000_000 or self.price_base_units % BASE_UNITS_PER_CENT:
            raise PaymentError("x402_price_must_be_positive_test_usdc_whole_cents")
        parsed = urlsplit(self.facilitator_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise PaymentError("x402_facilitator_requires_https")


class X402SettlementRecorder:
    """Persist reported settlement, independently verify it, then credit once."""

    def __init__(self, tools: FinanceToolClient, client: SupabaseClient,
                 verifier: BaseSepoliaVerifier, config: X402Config):
        if tools.prepare_only:
            raise PaymentError("evaluation_cannot_receive_payments")
        self.tools, self.client, self.verifier, self.config = tools, client, verifier, config

    async def reconcile(self, *, tx_hash: str, payer: str) -> dict[str, Any]:
        tx_hash, payer = transaction_hash(tx_hash), address(payer)
        recipient = address(self.config.pay_to_address)
        await self.tools.call("record_trace", {"event_type": "x402_settlement_reported", "payload": {
            "transaction_hash": tx_hash, "payer": payer, "recipient": recipient,
            "network": NETWORK, "amount_base_units": str(self.config.price_base_units),
            "verification": "facilitator_reported_not_yet_chain_verified"},
            "idempotency_key": f"x402:{tx_hash}:reported"})
        intent = TransferIntent(recipient, payer, self.config.price_base_units//BASE_UNITS_PER_CENT,
                                self.config.price_base_units, NETWORK)
        try:
            receipt = await self.verifier.verify(tx_hash, intent)
        except PaymentError as exc:
            await self.tools.call("record_trace", {"event_type": "x402_verification_pending", "payload": {
                "transaction_hash": tx_hash, "reason": exc.code}, "idempotency_key": f"x402:{tx_hash}:pending:{exc.code}"})
            retryable = exc.code in {"receipt_pending", "receipt_waiting_for_confirmations", "chain_rpc_unavailable", "chain_rpc_error"}
            if retryable:
                await self._queue_reconciliation(tx_hash, payer)
            return {"status": "pending_verification", "reason": exc.code, "transaction_hash": tx_hash, "retryable": retryable}
        text = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
        artifact = await self.tools.call("put_artifact", {"name": f"x402-{tx_hash}.json", "content": text,
            "content_type": "application/json", "idempotency_key": f"x402:{tx_hash}:artifact"})
        result = await self.client.rpc("record_finance_income", {**self.tools.scope.params(),
            "p_receipt": receipt, "p_artifact_path": artifact["artifact_path"],
            "p_content_sha256": hashlib.sha256(text.encode()).hexdigest()})
        return {"status": "confirmed", "transaction_hash": tx_hash, "receipt": receipt, "records": result}

    async def _queue_reconciliation(self, tx_hash: str, payer: str) -> None:
        scope = self.tools.scope
        key = "x402-verify:" + tx_hash
        filters = {"organization_id": f"eq.{scope.organization_id}", "run_id": f"eq.{scope.run_id}", "idempotency_key": "eq." + key}
        payload = {"source": "x402", "transaction_hash": tx_hash, "payer": payer}
        existing = await self.client.select("jobs", filters=filters, limit=1)
        if existing:
            if existing[0]["payload"] != payload:
                raise PaymentError("x402_job_idempotency_conflict")
            return
        try:
            await self.client.insert("jobs", {"organization_id": str(scope.organization_id), "run_id": str(scope.run_id),
                "command_type": "intake", "payload": payload, "idempotency_key": key,
                "available_at": (datetime.now(UTC)+timedelta(seconds=10)).isoformat()})
        except SupabaseError as exc:
            if exc.status != 409:
                raise
            existing = await self.client.select("jobs", filters=filters, limit=1)
            if not existing or existing[0]["payload"] != payload:
                raise PaymentError("x402_job_idempotency_conflict") from exc


async def reconcile_configured_income(tools: FinanceToolClient, client: SupabaseClient,
                                      payload: dict[str, Any]) -> dict[str, Any]:
    """Trusted worker intake branch. Public input cannot pick price or recipient."""
    from app.config import Settings
    settings = Settings()
    config = X402Config(settings.x402_pay_to_address or None, settings.x402_price_base_units, settings.x402_facilitator_url)
    config.validate()
    if not config.pay_to_address:
        return {"status": "blocked", "reason": "x402_receiver_not_configured", "retryable": False}
    tx_hash, payer = transaction_hash(payload.get("transaction_hash")), address(payload.get("payer"))
    prior = await client.select("trace_events", filters={"organization_id": f"eq.{tools.scope.organization_id}",
        "run_id": f"eq.{tools.scope.run_id}", "event_type": "eq.x402_settlement_reported",
        "payload->>transaction_hash": "eq." + tx_hash}, limit=1)
    if not prior:
        return {"status": "blocked", "reason": "unrecognized_x402_settlement", "retryable": False}
    reported = prior[0]["payload"]
    if reported.get("payer") != payer or reported.get("recipient") != address(config.pay_to_address) or reported.get("amount_base_units") != str(config.price_base_units) or reported.get("network") != NETWORK:
        return {"status": "blocked", "reason": "x402_recorded_scope_or_configuration_mismatch", "retryable": False}
    verifier = BaseSepoliaVerifier(settings.base_sepolia_rpc_url)
    try:
        result = await X402SettlementRecorder(tools, client, verifier, config).reconcile(tx_hash=tx_hash, payer=payer)
    finally:
        await verifier.close()
    return {**result, "status": "completed" if result["status"] == "confirmed" else "blocked"}


def create_x402_app(config: X402Config, *, recorder: X402SettlementRecorder | None,
                    resource_provider: Callable[[], Awaitable[dict[str, Any]]],
                    facilitator: Any = None, mount_path: str = "") -> FastAPI:
    """Mount at /x402; paid GET /sponsor-report sells an explicitly safe report.

    The factory never creates wallets/accounts or deploys an endpoint. A separate
    payer (e.g. official Wallet MCP's x402 tools) signs the actual authorization.
    """
    config.validate()
    if mount_path and (not mount_path.startswith("/") or mount_path.endswith("/") or any(char in mount_path for char in "?*#")):
        raise PaymentError("invalid_x402_mount_path")
    app = FastAPI(title="Director finance testnet sponsor report")
    configured = bool(config.pay_to_address and recorder)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"configured": configured, "network": NETWORK, "testnet_only": True}

    @app.get("/sponsor-report")
    async def sponsor_report(request: Request):
        if not configured:
            return JSONResponse({"status": "blocked", "reason": "x402_receiver_not_configured"}, status_code=503)
        if not getattr(request.state, "payment_payload", None):
            return JSONResponse({"status": "blocked", "reason": "x402_payment_middleware_not_applied"}, status_code=503)
        return {"report": await resource_provider(), "network": NETWORK,
                "settlement_evidence": "PAYMENT-RESPONSE header; financial credit requires independent chain verification"}

    if not configured:
        return app
    try:
        from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
        from x402.http.middleware.fastapi import PaymentMiddlewareASGI
        from x402.http.types import RouteConfig
        from x402.mechanisms.evm.exact import ExactEvmServerScheme
        from x402.schemas import AssetAmount
        from x402.server import x402ResourceServer
    except ImportError as exc:
        raise PaymentError("install_payments_extra_for_x402") from exc
    server = x402ResourceServer(facilitator or HTTPFacilitatorClient(FacilitatorConfig(url=config.facilitator_url, timeout=20)))
    server.register(NETWORK, ExactEvmServerScheme())

    async def on_settlement(context) -> None:
        result = context.result
        if not result.success or result.network != NETWORK or not result.payer:
            raise PaymentError("x402_settlement_response_requires_review")
        # Receipt absence/confirmations remain pending, with the transaction saved
        # durably. A later trusted call to reconcile finishes the same transaction.
        await recorder.reconcile(tx_hash=result.transaction, payer=result.payer)

    server.on_after_settle(on_settlement)
    routes = {f"GET {mount_path}/sponsor-report": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=address(config.pay_to_address),
            price=AssetAmount(amount=str(config.price_base_units), asset=USDC_ADDRESS,
                              extra={"name": "USDC", "version": "2"}), network=NETWORK)],
        description="Testnet event sponsor report access", mime_type="application/json")}
    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)
    return app

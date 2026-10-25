from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from app.payments.types import (
    CHAIN_ID,
    NETWORK,
    TRANSFER_TOPIC,
    USDC_ADDRESS,
    PaymentError,
    TransferIntent,
    address,
    transaction_hash,
)


class BaseSepoliaVerifier:
    """Independent JSON-RPC receipt verification; does not trust wallet success text."""

    def __init__(self, rpc_url: str = "https://sepolia.base.org", *, confirmations: int = 2,
                 transport: httpx.AsyncBaseTransport | None = None):
        parsed = urlsplit(rpc_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or not 1 <= confirmations <= 100:
            raise PaymentError("invalid_chain_verifier_configuration")
        self._http = httpx.AsyncClient(timeout=20, transport=transport)
        self._url, self.confirmations = rpc_url, confirmations

    async def close(self) -> None:
        await self._http.aclose()

    async def rpc(self, method: str, params: list[Any]) -> Any:
        try:
            response = await self._http.post(self._url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PaymentError("chain_rpc_unavailable") from exc
        if not isinstance(payload, dict) or payload.get("error") or "result" not in payload:
            raise PaymentError("chain_rpc_error")
        return payload["result"]

    async def network_status(self) -> dict[str, Any]:
        chain_id = int(await self.rpc("eth_chainId", []), 16)
        if chain_id != CHAIN_ID:
            raise PaymentError("rpc_mainnet_or_wrong_chain_denied")
        latest = int(await self.rpc("eth_blockNumber", []), 16)
        return {"network": NETWORK, "chain_id": chain_id, "latest_block": latest, "verification": "live_rpc_read"}

    async def verify(self, tx_hash: str, intent: TransferIntent) -> dict[str, Any]:
        tx_hash = transaction_hash(tx_hash)
        status = await self.network_status()
        receipt = await self.rpc("eth_getTransactionReceipt", [tx_hash])
        if receipt is None:
            raise PaymentError("receipt_pending")
        if transaction_hash(receipt.get("transactionHash")) != tx_hash or receipt.get("status") != "0x1":
            raise PaymentError("transaction_failed_or_hash_mismatch")
        try:
            block_number = int(receipt["blockNumber"], 16)
            block_hash = transaction_hash(receipt["blockHash"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PaymentError("malformed_receipt") from exc
        if status["latest_block"] - block_number + 1 < self.confirmations:
            raise PaymentError("receipt_waiting_for_confirmations")
        block = await self.rpc("eth_getBlockByNumber", [hex(block_number), False])
        if not isinstance(block, dict) or str(block.get("hash", "")).lower() != block_hash:
            raise PaymentError("receipt_block_not_canonical")
        # Verify actual USDC contract state, not an arbitrary token using USDC's name.
        decimals = await self.rpc("eth_call", [{"to": USDC_ADDRESS, "data": "0x313ce567"}, "latest"])
        if int(decimals, 16) != 6:
            raise PaymentError("usdc_decimals_mismatch")
        matches = []
        for log in receipt.get("logs", []):
            topics = log.get("topics", [])
            if str(log.get("address", "")).lower() != USDC_ADDRESS.lower() or len(topics) != 3 or str(topics[0]).lower() != TRANSFER_TOPIC:
                continue
            if log.get("removed") is True or str(log.get("transactionHash", tx_hash)).lower() != tx_hash:
                raise PaymentError("removed_or_mismatched_transfer_log")
            try:
                sender, destination = address("0x" + topics[1][-40:]), address("0x" + topics[2][-40:])
                amount = int(log["data"], 16)
                log_index = int(log["logIndex"], 16)
            except (KeyError, TypeError, ValueError) as exc:
                raise PaymentError("malformed_transfer_log") from exc
            if sender == intent.sender and destination == address(intent.destination):
                matches.append((amount, log_index))
        if len(matches) != 1 or matches[0][0] != intent.amount_base_units:
            raise PaymentError("exact_usdc_transfer_not_found")
        return {"provider_reference": tx_hash, "destination": intent.destination,
                "sender": intent.sender, "amount_minor": str(intent.amount_minor),
                "amount_base_units": str(intent.amount_base_units), "asset": "USDC",
                "token_address": USDC_ADDRESS, "asset_decimals": 6, "network": intent.network_alias,
                "status": "confirmed", "verification": "independent_json_rpc_receipt",
                "block_number": block_number, "block_hash": block_hash,
                "confirmations": status["latest_block"] - block_number + 1, "log_index": matches[0][1]}

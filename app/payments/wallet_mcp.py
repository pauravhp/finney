from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.payments.types import PaymentError, TransferIntent, address

OFFICIAL_WALLET_MCP = "https://wallet-mcp.coinbase.com"
ALLOWED_TOOLS = {"get_wallets", "send", "get_request_status"}


class CoinbaseWalletMCP:
    """Official remote Wallet MCP; write calls are single attempts with no retry."""

    def __init__(self, access_token: str | None, *, url: str = OFFICIAL_WALLET_MCP):
        if url.rstrip("/") != OFFICIAL_WALLET_MCP:
            raise PaymentError("only_official_coinbase_wallet_mcp_allowed")
        self._token, self._url = access_token, url

    @property
    def configured(self) -> bool:
        return bool(self._token)

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in ALLOWED_TOOLS:
            raise PaymentError("wallet_tool_outside_executor_allowlist")
        if name == "send":
            amount = arguments.get("amount")
            if set(arguments) != {"recipient", "amount", "asset", "chain"} or arguments.get("chain") != "base-sepolia" or arguments.get("asset") != "USDC" or not isinstance(amount, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,6})?", amount) or Decimal(amount) <= 0:
                raise PaymentError("wallet_send_must_be_exact_testnet_usdc")
            address(arguments.get("recipient"))
        if not self._token:
            raise PaymentError("coinbase_wallet_oauth_required")
        # The OAuth bearer remains in this trusted service, never a model tool.
        async with (
            httpx.AsyncClient(headers={"Authorization": f"Bearer {self._token}"}, timeout=60, follow_redirects=False) as http,
            streamable_http_client(self._url, http_client=http) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            discovered = {}
            cursor = None
            for _page in range(10):
                page = await session.list_tools(cursor=cursor)
                discovered.update({tool.name: tool for tool in page.tools})
                cursor = page.nextCursor
                if not cursor:
                    break
            tool = discovered.get(name)
            if tool is None:
                raise PaymentError("documented_wallet_tool_not_discovered")
            schema = tool.inputSchema
            if any(key not in arguments for key in schema.get("required", [])):
                raise PaymentError("wallet_tool_schema_changed")
            if schema.get("additionalProperties") is False and any(key not in schema.get("properties", {}) for key in arguments):
                raise PaymentError("wallet_tool_schema_changed")
            response = await session.call_tool(name, arguments)
            if response.isError:
                raise PaymentError("wallet_mcp_tool_error")
            if isinstance(response.structuredContent, dict):
                return response.structuredContent
            texts = [item.text for item in response.content if item.type == "text"]
            try:
                result = json.loads("\n".join(texts))
            except (ValueError, TypeError) as exc:
                raise PaymentError("wallet_response_requires_review") from exc
            if not isinstance(result, dict):
                raise PaymentError("wallet_response_requires_review")
            return result

    async def send(self, intent: TransferIntent) -> dict[str, Any]:
        await self.verify_sender(intent.sender)
        return await self.call("send", {"recipient": intent.destination, "amount": intent.usdc_decimal(),
                                        "asset": "USDC", "chain": "base-sepolia"})

    async def verify_sender(self, sender: str) -> None:
        wallets = await self.call("get_wallets", {})
        observed = self._wallet_addresses(wallets)
        if observed != {address(sender)}:
            # The documented send tool does not promise an explicit from-address
            # parameter. Reject an ambiguous/default wallet before creating any
            # approval request, rather than discovering a wrong sender afterward.
            raise PaymentError("connected_wallet_sender_unverified_or_ambiguous")

    @staticmethod
    def _wallet_addresses(payload: Any) -> set[str]:
        result = set()
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key in {"address", "walletAddress", "wallet_address"} and isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{40}", value):
                    result.add(address(value))
                elif isinstance(value, (dict, list)):
                    result.update(CoinbaseWalletMCP._wallet_addresses(value))
        elif isinstance(payload, list):
            for item in payload:
                result.update(CoinbaseWalletMCP._wallet_addresses(item))
        return result

    async def request_status(self, request_id: str) -> dict[str, Any]:
        return await self.call("get_request_status", {"requestId": request_id})

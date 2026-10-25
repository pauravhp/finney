# Coinbase adapter choice

The implementation calls **Coinbase's official Wallet MCP**, not the separate
exchange Coinbase MCP. Endpoint: `https://wallet-mcp.coinbase.com`, authenticated
with an externally connected OAuth token. It discovers current tools/schemas
before calling documented `get_wallets`, `send`, and `get_request_status`.
The x402 seller uses the official SDK/facilitator. An external sponsor can use
Wallet MCP's documented x402 buyer tools against our testnet-only endpoint.

Wallet MCP documents Base Sepolia sends and x402, so no CDP SDK wrapper is needed.
Each send returns a human wallet approval URL; application two-person approvals
are checked before requesting that wallet operation. These application decisions
are **not cryptographic multisig**. Wallet approval is an additional provider step.

No signer/private key is given to Hermes or the improver. The worker payment
service owns the authenticated MCP connection. Credentials are not configured in
source, examples, or artifacts. Without OAuth, execution returns blocked.

Primary sources checked October 25, 2026:

- [Official Wallet MCP](https://docs.cdp.coinbase.com/ai-agents/coinbase-for-agents/wallet-mcp)
- [Coinbase's x402 Python FastAPI example](https://github.com/coinbase/x402/blob/main/examples/python/servers/fastapi/main.py)
- [Circle USDC contract addresses](https://developers.circle.com/stablecoins/usdc-contract-addresses)

The production code is in `app/payments/` so it is included by the Python package.

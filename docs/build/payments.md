# Testnet payment build evidence

Status: implementation available; live settlement **not verified**. No Coinbase
OAuth connection, test-fund treasury, receiving account or second human approval
session has been provided. No funds moved during this work.

## Actual integration choice

Use Coinbase's **official Wallet MCP** over Streamable HTTP at
`https://wallet-mcp.coinbase.com`. This is distinct from the exchange Coinbase MCP.
Current official documentation explicitly supports `send` on Base Sepolia and
x402 on Base/Base Sepolia, so a custom MCP facade around CDP SDK is unnecessary.

The client discovers current tool schemas before calling documented tools:
get_wallets, send, get_request_status. Unknown tools/schema changes fail closed. There is no
invented Coinbase REST endpoint or blind tool retry. OAuth bearer credentials
stay in the trusted service, never Hermes or the improver.

Primary sources checked October 25, 2026:

- [Official Wallet MCP](https://docs.cdp.coinbase.com/ai-agents/coinbase-for-agents/wallet-mcp)
- [Official Wallet MCP approval reference](https://github.com/base/skills/blob/master/skills/base-mcp/references/approval-mode.md)
- [Official x402 Python FastAPI example](https://github.com/coinbase/x402/blob/main/examples/python/servers/fastapi/main.py)
- [x402 Python SDK source](https://github.com/coinbase/x402/tree/main/python/x402)
- [Circle's USDC addresses](https://developers.circle.com/stablecoins/usdc-contract-addresses)

The SDK version tested is x402 2.25.0; optional dependency
`x402[evm,httpx]==2.25.0`. Existing mcp/httpx/FastAPI dependencies support the
wallet client and independent receipt verifier. The CDP SDK is not used.

Sponsors pay the configured testnet-only seller from an external x402 buyer;
Wallet MCP documents initiate_x402_request/complete_x402_request for that role.
Those buyer tools also support mainnet and do not document an explicit network
binding parameter. They are deliberately outside this executor's allowlist.
Our service receives x402 payments rather than creating arbitrary paid URL requests.

## Integration APIs

`await app.payments.executor.execute_configured_payment(tools,proposal_id)` is
the coordinator's execute_payment job entry. Configuration comes only from
`app.config.Settings`:

- COINBASE_MCP_TOKEN: externally obtained OAuth bearer, protected secret.
- COINBASE_MCP_URL: blank or https://wallet-mcp.coinbase.com only.
- COINBASE_SENDER_ADDRESS: explicitly connected sender wallet.
- BASE_SEPOLIA_RPC_URL: defaults to https://sepolia.base.org.
- COINBASE_MAX_TEST_USDC_BASE_UNITS: defaults to 100000000 (100 test USDC).
- X402_PAY_TO_ADDRESS, X402_PRICE_BASE_UNITS (default10000, 0.01 test USDC),
  X402_FACILITATOR_URL (default https://x402.org/facilitator).

An approved outgoing action must bind these exact fields in its immutable hash:

```json
{
  "type":"payment", "currency":"USD", "amount_minor":"1",
  "asset":"USDC", "amount_base_units":"10000", "asset_decimals":6,
  "token_address":"0x036CbD53842c5426634e7929541eC2318f3dCF7e",
  "network":"eip155:84532", "sender":"<connected EVM address>",
  "destination":"<verified recipient address>",
  "obligation_id":"<uuid>", "obligation_version":1
}
```

Trusted proposal code can call `build_testnet_payment_action` with obligation ID,
version, integer amount, recipient and configured sender. It derives the contract,
decimals and base-unit conversion before the immutable approval hash is created.

USD minor units mean cents; one cent equals 10000 USDC base units. Floats,
mismatched conversion/contract/decimals, mainnet, arbitrary assets and excessive
test amounts are rejected before sending. The official send API does not promise
an explicit source-address argument; the adapter requires a uniquely identified
connected wallet matching the approved sender. Ambiguity blocks before effects.

The executor reserves the two-human-approved action, reads its **current** durable
payment status, uniquely claims submitting, and calls remote send once. It returns
the actual provider approval URL/request ID as blocked/awaiting wallet approval.
Resume polls that request; submitting/uncertain without a request ID requires
investigation. No timeout or repeated job sends the transfer again. Once a hash
exists, independent JSON-RPC verifies chain84532, canonical successful receipt,
two block confirmations, actual USDC contract decimals and exactly one Transfer
log with approved sender/recipient/base-unit amount. Only then does confirm_payment
atomically settle the obligation and journal.

Application decisions are not cryptographic wallet multisig. Wallet approval is
an additional human provider action. The application validates authority before
creating that provider request; it cannot revoke an already issued remote approval
URL through an undocumented API. This boundary must remain explicit in demos.

## x402 seller and incoming reconciliation

`create_x402_app(X402Config(...),recorder=...,resource_provider=...,mount_path='/x402')`
returns a mountable FastAPI app. GET /x402/sponsor-report is protected with the
official exact EVM x402 middleware; /x402/health reports configuration. A missing
receiver returns503. The resource provider must return an intentionally safe
sponsor report, never an implicit dump of private records. No deployment occurs
in this factory.

The facilitator settles the signed x402 authorization. A hook saves its reported
transaction, then independently checks the actual USDC transfer. Missing receipts
or insufficient confirmations stay pending and enqueue a delayed durable intake
job with `{source:'x402',transaction_hash,payer}`. The worker calls
`reconcile_configured_income(tools,db,payload)` and handles retryable pending results
using queue.fail(retryable=True); existing queue backoff caps attempts at five.
No financial success is inferred from a facilitator's success text alone.

Reconciliation requires a prior scoped server-reported settlement and binds price
and recipient to server configuration. A visitor cannot select those via payload.
The new `record_finance_income` RPC atomically stores the source, global receipt
claim and balanced cash/sponsor_income journal. A network/transaction/log tuple
cannot be credited to a second organization or run. Unknown opening cash remains
unknown; an incoming micropayment does not establish the complete treasury balance.

Second migration:
`supabase/migrations/202610250002_payment_income.sql` SHA-256
`2f93d83e6abaa93393ee7af6d20e4b8954acc4ca99615826dd28116164e60ad8`.
It does not modify the frozen first migration.

## Evidence, failures and lessons

- Public read-only checks: x402.org/facilitator/supported returned200 and advertised
  exact/eip155:84532. sepolia.base.org eth_chainId returned200,0x14a34.
- Running the actual BaseSepoliaVerifier.network_status returned chain84532,
  latest block49870584. An actual eth_call on Circle's test USDC contract returned
  decimals6. These verify connectivity/configuration, **not settlement**.
- Initial payment unit tests:18 passed. Official x402 SDK protocol tests use an
  explicitly fake facilitator/signature and do not represent signed payments.
- Local SQL tests applied both migrations and verified one incoming receipt posts
  once, cross-run reuse is rejected, wrong-chain/base-unit conversion fails
  atomically, and browser identity cannot call the income RPC.
- Review found a historical idempotency-result trap: reserve RPC replay returns
  its original reserved snapshot. Fixed the executor to read current payment state
  after reservation. Tests cover a timeout, subsequent retry with zero additional
  sends, wallet approval polling, confirmed replay and sender ambiguity.
- Mount test initially expected an omitted prefix to bypass middleware. The actual
  SDK also checks decoded paths and correctly returned402. Corrected the test to
  cover supported default and explicit prefixes, plus a genuinely wrong prefix;
  the route-level payment-state guard prevents returning the report in that case.
- An independent verifier must inspect token transfer logs, not the transaction's
  top-level to/value or a wallet success label: smart wallets and x402 facilitators
  submit contract calls. Wrong contract/sender/amount, failed receipt and noncanonical
  block tests all reject a claimed success.

No hosted Supabase requests were made by this builder. The coordinator alone
managed hosted migration/access checks. Authentication failures must halt cloud
connection attempts immediately; do not guess URL/credential variants or retry.

Final combined command (all three migrations on an isolated PostgreSQL cluster):

```sh
FINANCE_TEST_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres .venv/bin/pytest -q tests/test_finance_domain.py tests/test_storage_http.py tests/test_finance_postgres.py tests/test_payments.py tests/test_payments_x402.py
.venv/bin/ruff check app/finance app/storage app/payments tests/test_finance_domain.py tests/test_storage_http.py tests/test_finance_postgres.py tests/test_payments.py tests/test_payments_x402.py --output-format concise
```

Result: **54 passed in 1.98s; all lint checks passed**. Eighteen tests exercise
actual PostgreSQL transactions/RLS/functions. Twelve are domain/HTTP fixture tests
and twenty-four are payment/protocol tests. A final targeted run after extracting
the trusted action preparation helper passed **25 tests**, including the real SQL
competing-executor scenario. Those two executors share one proposal and an
explicitly fake delayed wallet; only one remote send request is issued.

Pending x402 tests prove that a not-yet-confirmed transfer creates one delayed
durable job and no ledger credit. Public reconciliation cannot accept an arbitrary
transaction without its original scoped server settlement record. Receipt retry
never resubmits a transfer.

Final boundary refinement: unrestricted Wallet MCP buyer/sign/swap/batch tools
are outside the service allowlist. Raw send calls also enforce Base Sepolia,
USDC and exact decimal quantities. The new regression rejects mainnet before
making a network request. Its first run exposed a test fixture that expected an
OAuth error while supplying an invalid empty transfer; the earlier validation
correctly rejected that input first. Updated the fixture to a valid testnet
transfer so it tests missing OAuth independently. Retest: **25 payment tests passed;
all payment lint checks passed**. No live settlement claim follows from this.

Final combined retest after that boundary change: **55 passed in 1.84s**
(18 PostgreSQL integration, 12 domain/HTTP, 25 payment/protocol). All provider
limitations above remain unchanged.

## Remaining live gates

External OAuth setup/tool discovery against an authenticated Coinbase wallet,
funded test sender and receiver, two actual human app approvals, wallet approval,
actual transfer hash, independent chain receipt, a signed x402 buyer request and
incoming ledger confirmation remain unverified. Unit fixtures are explicitly
labeled. No wallet-level multisig or complete live demo pass is claimed.

# Coinbase OAuth implementation receipt

October25,2026 UTC. No external client registration, OAuth consent, token
exchange/refresh, wallet/account creation, wallet tool call or transfer occurred
during this implementation. Migration011 has not been applied to hosted Supabase
by this builder.

Official primary evidence: the
[Coinbase Wallet MCP guide](https://docs.cdp.coinbase.com/ai-agents/coinbase-for-agents/wallet-mcp)
describes OAuth and a distinct Wallet confirmation for writes. Two real read-only
metadata requests to the official Wallet MCP host returned404 for protected
resource metadata and200 for authorization-server metadata. The latter advertises
same-origin authorize/token/register endpoints, authorization-code/refresh grants,
S256 PKCE, public-client token auth and transact/escalate scopes. This establishes
advertised compatibility, not acceptance of this app's registration or redirect.
See the discovery receipt (`evidence/coinbase-oauth-discovery.json`, private receipt).

The installed Python MCP1.30.0 OAuthClientProvider/TokenStorage implementation was read
before building this split begin/complete flow. The app uses the SDK's validated
OAuth metadata/client/token models and PKCE generator, with stricter known-issuer
and endpoint checks. It does not read/write personal Hermes, Codex or MCP files.
Pending client/PKCE state and grants use the existing scope-bound authenticated
encryption in protected Supabase rows. A service-only transaction rechecks/locks
the private run and current director, consumes the claimed pending state and
commits token plus connection metadata atomically.

Expired token refresh uses an atomic one-time claim and a version/claim CAS.
Timeouts or failures retain the claim; reauthorization is required instead of
blindly rotating the old refresh token again. A concurrent reconnect resets the
claim and changes the stored version, so a stale refresh cannot overwrite it.
The actor/improver has no credential loading or signing tool.

23new fixture/local SQL tests pass;157combined kernel/budget/auth tests pass.
Changed Python files pass Ruff. Tests cover issuer/endpoint/registration
compatibility, PKCE matching, encrypted persistence, exact callback/scope/replay,
removed directors and demo denial, bounded errors, token rotation, uncertain
refresh behavior, actual SQL atomic commit, two-worker claim races and reconnect
CAS. Provider HTTP is explicitly simulated in these tests; only metadata
discovery above contacted Coinbase.

Command:
`FINANCE_TEST_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres uv run --extra dev --extra payments pytest -q tests/test_coinbase_authorization_connect.py tests/test_finance_budget.py tests/test_finance_runtime_guards.py tests/test_finance_postgres.py tests/test_finance_approval_policy.py tests/test_finance_domain.py`.

The first SQL fixture run used a timezone-dependent bare epoch date; it was
corrected to explicit UTC, matching production's claimed-pending marker. Its
constant state hash was also made unique per fixture run. Neither correction
relaxed the production scope, expiry or single-use guards.

The remaining actual owner step is to open the generated URL, authorize their
existing wallet and paste the resulting loopback callback into the hidden
complete prompt. Wallet identity/funding/payment settlement are separate gates.

## Coordinator live follow-up

After the local checks, migration011 was applied to hosted Supabase. A single
actual `begin` invocation checked the current private event/director, read the
official discovery document, registered Finney's public PKCE client successfully
and persisted encrypted pending state. Its authorization invitation is stored
only in ignored private state and was presented to the owner. No consent/token,
wallet identity, funding or payment result is inferred from registration. The
owner may return the single-use callback through a concealed the owner’s password manager field; it
must still pass the same scope/state/expiry/PKCE checks as hidden terminal input.

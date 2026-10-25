# Connect the event's existing Coinbase Wallet

Use the app-owned Wallet MCP OAuth flow. No bearer token needs to be extracted
from a browser or another application's configuration. Coinbase documents OAuth
connection and its separate per-action Wallet approval in the
[official Wallet MCP guide](https://docs.cdp.coinbase.com/ai-agents/coinbase-for-agents/wallet-mcp).

Apply migration011 along with the earlier migrations. Configure the event's
SUPABASE_URL, backend key, FINANCE_ORGANIZATION_ID, FINANCE_RUN_ID and
FINANCE_TOKEN_ENCRYPTION_KEY in the protected worker environment. The event must
be private and active; the supplied director UUID must be a current director.
Public demo runs cannot receive this grant.

The installed CLI provides:

```sh
finance coinbase-connect --director-user-id DIRECTOR_AUTH_UUID
finance coinbase-connect --complete
finance coinbase-connect --inspect
```

The first command registers an app-owned public OAuth client only when Coinbase
advertises compatible registration, S256 PKCE and public-client token exchange.
It prints an authorization URL. Open that URL, sign in to the existing Coinbase
Wallet account and approve the connection. If an account/wallet would need to be
created, that remains a separate owner action; Finney does not create one.

Coinbase redirects to
`http://127.0.0.1:8768/oauth/coinbase/callback`. A local callback listener is not
required for this split flow: copy the full resulting address even if the browser
shows a connection error. Run the second command in an interactive terminal and
paste that address into its hidden prompt. Complete within ten minutes. Do not
put the callback, authorization code or tokens in chat, command arguments or logs.

The inspect command only reads wallet addresses and marks multiple/absent choices
as ambiguous. It does not choose a sender or send funds. Configure the verified
single sender separately before testnet execution.

Successful completion means the OAuth credential was encrypted and committed for
this event/director. Wallet identity/sender ownership, Base Sepolia support,
funding and settlement still require their own checks. The consent requests
Coinbase's advertised transact/escalate scopes; Finney independently restricts
payment tools to its approved testnet workflow. Coinbase Wallet's own transaction
approval is still required in addition to the event's configured human approvals.

The worker loads the encrypted token and refreshes it when necessary. Refresh
requests use one durable claim and conditional commit, so an uncertain response
is never retried using the old refresh credential. Reconnect after an expired
unrefreshable grant, an uncertain refresh or a revoked authorization. Concurrent
refresh/reconnection cannot overwrite a newer grant. A removed director's grant
is not loaded or refreshed.

Errors expose only an application code, HTTP status and a recognized standard
OAuth error (when present). If Coinbase rejects dynamic registration or the
loopback redirect, retain that exact safe error as an external provider gate.
Do not borrow another app's client, read its private config or bypass consent.
The legacy explicitly configured COINBASE_MCP_TOKEN remains optional compatibility
input; the normal connect flow does not require it.

Integration contract:

- `begin(settings,director_user_id)` returns authorization_required and a public
  authorization_url. It is an explicit external registration operation.
- `finish(settings,callback_url)` exchanges one code and atomically commits the
  encrypted grant. The CLI collects callback_url with getpass in a real TTY.
- `load_access_token(settings)` is for the trusted executor only. It returns a
  token or None when no stored grant exists; it never gives tokens to the actor.
- CoinbaseAuthorizationError exposes code/status/provider_error, never raw
  response bodies or error descriptions.

Current verification is recorded in [the OAuth receipt](build/coinbase-oauth.md).

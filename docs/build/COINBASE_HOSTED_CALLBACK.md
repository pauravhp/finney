# Hosted Coinbase connection handoff

Owner requested a fresh Coinbase connection usable from a different machine.
Implemented separately from the active optimizer and branding work, based on
public baseline `8cf5b50`. This change authorizes a wallet connection only; no
payment, funding, transaction approval or settlement result is implied.

The configured `COINBASE_REDIRECT_URI` is pinned through client registration,
authorization, encrypted pending state, callback claim and token exchange. It
must be the exact `/oauth/coinbase/callback` route on a public HTTPS hostname.
Legacy local loopback setup remains compatible. Provider registration cannot
substitute another redirect. Encrypted stored clients retain their registered
redirect when a later worker loads or refreshes the grant.

The deployed callback is a minimal handoff page, without backend keys or external
resources. A nonce-based CSP permits only its own script/style. It removes the
code/state query from browser history immediately, disables caching, referrers,
framing and indexing, and offers copy/manual-copy controls. An absent, denied or
malformed callback does not claim connection. The owner returns the short-lived
callback via a hidden prompt or an agreed concealed password-manager field;
the worker performs the existing PKCE exchange and encrypted Supabase commit.

Migration020 replaces only `connect_coinbase_wallet`'s loopback-only receipt
predicate with loopback-or-hosted-HTTPS support. Existing service-only grants,
private active run, current director, scope, claimed-state age, atomic encrypted
commit and replay checks remain. Earlier applied migrations are unchanged.
The learning integration owns migrations017–019; this branch does not modify
or reapply them. Deploy this small web change before generating the ten-minute
authorization invitation. The worker must include these Coinbase changes before
using the new hosted grant for payments; no runtime switch is part of this work.

Validation:69 Python authorization/approval tests passed,2 pre-existing skips;
Ruff passed; Next production build/typecheck passed;4 desktop/mobile Playwright
checks passed. Fixtures test hosted registration/exchange, changed callback,
provider redirect substitution, invalid configurations, real local PostgreSQL
commit/replay rejection and HTTPS receipt restrictions. Browser tests confirm
query removal, strict headers, zero follow-up network requests, hidden manual
callback, valid/error states and no horizontal overflow.

Initial browser checks caught Next's global Referrer-Policy overriding the route
header; a callback-specific config rule fixes it. Desktop/mobile captures were
reviewed inline because this side conversation prohibits subagents. The narrow
page inherits the dashboard palette and controls and uses a system font to keep
the sensitive handoff independent of font/resource requests. No branding changes.

Live deployment, migration and invitation receipts are kept only in ignored
private state; invitation/callback values are never source or test fixtures.

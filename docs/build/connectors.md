# Connector verification log

## Gmail / CSV / token encryption

- Implemented read-only Gmail OAuth + PKCE, exact selected-query full sync,
  label-scoped history sync, pagination limits that refuse cursor advancement,
  MIME/attachment evidence parsing, source hashes and safe provider errors.
- Implemented scope-bound authenticated encryption for token storage and exact
  CSV amounts/provenance. Imported rows remain reported evidence, not settlement.
- First `uv run pytest tests/test_connectors.py -q`: **6 passed, 1 failed**.
  OAuth state leaked through the dataclass's authorization URL representation
  despite the state field being `repr=False`. Fix: exclude the URL from repr too.
  This was unit-only test data; no real credentials or personal mail were involved.
- Retest `uv run pytest tests/test_connectors.py -q`: **7 passed**. HTTP responses in these tests are
  explicit unit fixtures; live Gmail OAuth and ingestion remain unverified.

Reusable lesson: redact credential-bearing composites as well as individual
secret fields. A safe token field does not make a containing URL safe to log.

## Isolated Hermes mailbox bridge — October 24 follow-up

The default Gmail transport now invokes the pinned Hermes Google Workspace setup
and client helpers in this application's dedicated runtime. The source is hash
verified. Each request has a fresh temporary HOME/HERMES_HOME/XDG_CONFIG_HOME,
restricted files and a minimal environment; credentials travel through stdin,
never arguments or inherited environment. Only readonly Gmail routes are exposed;
there is no actor shell, mail-send, gws or plugin loading. Source is unchanged.
This is trusted-code capability isolation, not a host OS security sandbox.

`finance gmail-connect` begins Desktop OAuth with readonly scope/PKCE; `--complete`
reads the full callback through a hidden terminal prompt. Encrypted pending state
is stored in Supabase and consumed once with scope/expiry checks. Active director
and private-run authority is checked again before token exchange and at commit.
Migration 007 atomically updates encrypted credentials and connection metadata,
resets cursors, and emits the existing scoped audit notification. Its real hosted
application succeeded after 27 local PostgreSQL tests passed. It changes no money.

The existing intake preserves label filtering, MIME parsing, pagination boundaries,
source deduplication and queue-before-cursor behavior. Native failures never select
another profile or silently fall back to legacy HTTP. Legacy browser OAuth remains
an explicit option. The configured label is an application restriction; Google
readonly authorization itself permits mailbox reads. PDF/OCR remains unavailable.

Observed failures and corrections:

- Fixture-only tests initially hid a state-length mismatch: upstream OAuth uses
  30-character state values, while the first auth helper required at least 32.
  Actual pinned local authorization URL generation exposed the mismatch. The
  helper now accepts the real upstream value and retains full state comparison.
- Browsers normalize localhost callbacks with a trailing slash. Both bridge and
  helper now accept the empty/root path only, retaining exact origin/code/state
  validation. No arbitrary path, redirect, scope or endpoint is accepted.
- An initial import smoke generated three bytecode files in the pinned source
  directory. Only those generated files were removed. The smoke now disables
  bytecode, production already uses `-B`, and the exact source hash was reverified.
- The legacy unconfigured callback test assumed 503 for all backends. Native
  configuration intentionally returns 409 with CLI guidance; both explicit
  backend behaviors are now checked. An import-order lint failure was corrected.

Final independent run: **282 Python tests + 10 subtests**, **10 web unit tests**,
**4 browser checks**, production build/TypeScript, Ruff and Impeccable detector
passed. The real pinned helper generated OAuth URLs offline using an invalid
fixture client; no Google consent or mailbox calls occurred. Existing UI browser
checks cover unconfigured states, not real Google sessions. Live acceptance still
requires the owner's Desktop client, encryption key, shared event and consent.
See `evidence/hermes-gmail-implementation.json` and `../AUTH_SETUP.md`.

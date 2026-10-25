# Acceptance evidence

## Current completion pass — October 24, 2026 Pacific

Sixteen hosted migrations are applied. Latest complete Python run:639 tests plus
28 subtests; Ruff passed. Web:48 unit tests, production build/TypeScript and15
desktop/mobile browser checks passed, with11 explicit skips (ten optional Auth
fixtures and one desktop-only exclusion). Independent Impeccable review closed its
one long-name wrapping finding. See [validation](../VALIDATION.md) for current
limits. Raw receipts referenced below are retained privately and excluded from
the public repository; these summaries distinguish real execution from fixtures.

| Actual live check | Result | Receipt |
|---|---|---|
| Existing owner sign-in → budget proposal/approval → PDF upload → Storage → isolated Hermes review → Jev → persisted finding → close report | Passed; synthetic financial input, real execution, cash remains unknown | `evidence/live-e2e-browser.json`, `evidence/live-e2e-jobs.json` |
| Authenticated private Realtime broadcast matched to exact audit event | Passed | `evidence/live-realtime.json` |
| Native browser original-PDF download matches uploaded bytes | Passed | `evidence/live-original-download.json` |
| Real Claude vision on synthetic receipt image | Passed; reported evidence, human verification required, one call reserved | `evidence/live-ocr-acceptance.json` |
| Guided demo seed → two actual expense/sponsor reviews | Passed; source hashes verified, no seeded output/cash/payment | `evidence/live-guided-jobs.json` |
| Automatic learning on real traces | Ran, rejected after diagnosis; no live gain, candidate or promotion from these attempts | `evidence/live-e2e-jobs.json`, `LEARNING_FALSE_NEGATIVE.md` |
| Actual Ask Finney form → director-message worker | Passed after separating conversational responses from financial decisions; provider text/provenance rendered, financial records unchanged | `DIRECTOR_CONVERSATIONS.md` |
| Fresh frozen financial review after trace-contract observer | Blocked: three blockers had no supporting references; Jev/reviewer/evaluation never ran, no retry or promotion | Private observed-phase summary |
| Coinbase official OAuth client registration | Succeeded; owner consent/token/wallet/funding/settlement pending | `coinbase-oauth.md`; invitation stays in private state |
| Public Vercel deployment / anonymous visitor access | Not performed | Hosting credentials and anonymous Auth/anti-abuse configuration remain open |

The actual empty Gmail label is connected and scheduled through isolated Hermes.
No nonempty live mail intake is claimed. Personal Hermes remains independent.
The first live PDF attempt failed because its idempotency key exceeded200 chars;
the fixed73-character digest passed actual SQL coverage and the same upload was
retried successfully. The original failure audit/browser receipt remains archived.
Original preexisting rejected candidate and offline regrade are also preserved.

## Historical first-pass receipt (superseded by current evidence above)

First implementation pass verified October 24, 2026, Pacific. This is not yet a
completed public live demonstration. Coordinator independently ran the final
local checks and the hosted checks listed below.

| Layer | Current status | Evidence |
|---|---|---|
| Python suite | Passed: 352 tests + 10 subtests | `FINANCE_TEST_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres uv run --extra dev --extra payments pytest -q`; includes real isolated PostgreSQL integration, explicitly simulated HTTP fixtures, and packaging/scheduler tests |
| Web checks | Passed: 21 unit tests, 4 current unconfigured browser checks, production build/TypeScript; earlier 10 Auth fixture checks | Coordinator ran `npm test`, `npm run build`, `npm run test:browser`; browser coverage includes explicit SDK fixtures, not live authenticated sessions |
| Static checks | Passed | `uv run ruff check app tests`, `git diff --check` |
| Installation/independence | Clean wheel + pinned public runtime passed | `packaging.md`, `runtime.md`; own `.runtime/hermes-source` and `.runtime/hermes-venv`, no personal Hermes profile/config edits |
| Kernel financial/authority checks | Passed locally | `kernel.md`; balances, CAS/version checks, distinct human identities, duplicate protection, private Storage positive and negative scope checks |
| Gmail/CSV/token behavior | Local regression checks passed | `connectors.md`, `tests/test_finance_review.py`; label-only intake, source/case crash recovery, queue-before-cursor, reconnect reset, callback races and exact amounts |
| Hermes/Jev real calls | Passed | `evidence/hosted-runtime-smoke.json`, real provider IDs and stored traces; explicit synthetic financial inputs |
| Hosted queue -> worker -> review | Passed on first lease | `evidence/hosted-worker-smoke.json`; actual job completed, case version2/awaiting_evidence, prepared review stored; no payment |
| Hosted Supabase | Eight migrations applied; actual source/Storage/report operations and duplicate intake passed | Public tables have RLS, bucket private; anonymous actual API read denied. Migration 006 receipt/checksum and scalar identity policy verified live; migration 007 atomic Hermes grant storage applied. Positive authenticated Storage policy checked on local PostgreSQL; real authenticated browser Storage path still pending |
| Hermes Gmail bridge | Implemented, local integration tests passed | Pinned upstream auth URL generation ran offline with fixture credentials; no real consent or mailbox ingestion. See connectors.md |
| Native Gmail grant/profile/intake | Passed through isolated Hermes with reused readonly grant | Actual first durable job completed; selected label is empty. New browser OAuth consent flow is not claimed tested |
| Coinbase testnet settlement | Not verified | Credentials/configuration pending |
| Live generated skill change/evaluation | Executed, rejected, baseline unchanged | `evidence/hosted-improvement-attempt.json`: genuine candidate and six real paired actor runs. Original 0/3 scores invalidated by two grader defects, not accepted as model performance |
| Corrected evaluation diagnosis | Offline regrade only: 3/3 both, 13 tool calls both, no measured gain | `evidence/hosted-improvement-offline-regrade-v2.json`; original result untouched. No untouched transfer case was run and no promotion occurred. Fresh evaluator/suite versions are finance-evaluator-v2 / organizer-expenses-blockers-v4 |
| Vercel deployment | Not performed | Build/preview verification first |

Unit tests with injected HTTP fixtures establish local behavior only. Live provider
checks must retain actual provider references and timestamps without credentials.

That historical integrated run included 27 PostgreSQL tests, membership identity changes,
atomic Hermes mailbox connection and authority checks. Actual Gmail and browser sign-in are
still unverified; see `connectors.md` for the tested native boundary.

## Historical first-pass gates and product limits

- Google Desktop OAuth client/consent for Hermes Gmail; the director alone grants
  the event mailbox. Dashboard Google SSO was removed at user request; it now uses
  regular Supabase email/password. Hosted settings confirm Email enabled, signup
  enabled and email confirmation required; actual browser sign-in is pending.
- The `director-finance` Gmail label was actually created with user authorization;
  the finance app has not yet read it. New OAuth credentials and the token
  encryption key are not present in the vault. One attempted vault key creation
  failed; a subsequent metadata check confirmed no key was created. No secret
  value was printed or stored in source/local output.
- Real authenticated browser/RLS/Realtime flow and two actual human approvals.
- Coinbase OAuth, owned testnet wallets/funding and signed x402/payout settlement.
  Public chain/facilitator reads passed; these are not payment evidence.
- Vercel hosting/account configuration; no deployment, GitHub publication or
  outreach occurred. No inference worker or web server was left running merely
  to imply readiness.
- Actual measured improvement and transfer remain unproved. Never relabel the
  offline regrade as fresh inference or the rejected change as promoted.
- Gmail attachment references are retained, but PDF/image extraction/OCR is not
  implemented. Current usable evidence is text/JSON and explicit CSV records.
- Budget/finance core is opening snapshots, cash/obligation forecasts, proposed
  spending/reimbursement actions and reports; full tax filing, bank connectivity,
  invoice-document OCR and broader vendor communication are not implemented.

## Incident resolution

See `INCIDENT-001-database-auth.md`: coordinator's repeated login diagnostics
triggered a temporary IP ban. User unbanned and corrected the URI; one controlled
TLS read-only check succeeded, followed by successful migrations. Failed probes
were stopped/removed; no data/schema changes preceded the successful connection.


## Email/password authentication follow-up

User cancelled dashboard Google SSO. The frontend now uses Supabase email/password
sign-in and signup; no-session signup stays pending confirmation. Shared-event
setup requires two distinct confirmed nonanonymous email/password identities,
including real participants whose accounts the owner provisions confirmed.

A single read of hosted Auth settings confirmed Email enabled, signup enabled,
confirmation required, Google disabled. No provider settings, accounts or mail
were changed. See `evidence/hosted-auth-settings.json`. Real browser authentication
and confirmation delivery remain unverified. Gmail's isolated Desktop OAuth is
separate and still awaits the director's grant.

Coordinator reran all Python checks (294 + 10 subtests) and 13 web unit tests,
reviewed the new auth code/tests and desktop/mobile screenshots, and verified the
restored production build contains no fixture origin. Web builder passed 4 normal
browser checks and 10 explicit Auth SDK fixture browser checks plus production
build/TypeScript; these never contacted a live Auth service or sent email.

Two browser-test defects were fixed: a broad alert selector also matched Next's
route announcer, and fixture CORS headers did not expose the API version used by
the Supabase SDK to interpret error codes. Assertions are now scoped to the form,
and fixtures match the SDK's header contract. The fixture test runner restores the
normal production build in finally, including when a test fails. Lessons concern
test accuracy; they do not establish real email delivery or a real user session.

## Owner-authorized live account and sign-in

The owner explicitly authorized creating a test user using their own email,
generating a password, storing it in their vault, and completing confirmation.
An admin read found no existing user before creation. A new Login item was written
and read back in 1Password before signup; no password was printed or persisted in
source. Real Supabase signup succeeded, the actual confirmation message arrived,
and its project-matched signup link was consumed (303). Admin readback confirmed
the email. No manual confirmation override or global auth-setting change was used.

A fresh browser used the real app email/password form against hosted Supabase,
received a session cookie, and successfully called `/api/finance/scopes` through
the actual server (200, zero memberships). No SDK/network fixtures, tracing, or
saved browser session were used. The temporary server was stopped. See
`evidence/hosted-auth-live.json`. Account IDs and vault references remain only in
private/internal setup records, not this public evidence file.

This closes live owner signup/email confirmation/password sign-in/server-session
acceptance. It does not establish public email delivery, a second human approver,
a shared finance event, positive event Storage/Realtime, or native Hermes Gmail
consent. Signup called the real provider API; app PKCE confirmation callback was
not exercised. The connected Gmail plugin read this one confirmation message;
that does not grant the finance worker access to the mailbox.

The exact confirmation subject differed from the initial narrow search. A bounded
sender search found the current message; no email was resent. 1Password write
capability is now verified using `op item create -` with JSON on stdin; the earlier
unclassified key-creation failure was not proof that vault access was read-only.

## Director, native Gmail and configurable approval follow-up

Owner is an actual director of a private durable event. Director-only bootstrap
requires no placeholder approver. The user's existing personal readonly grant was
found in a custom mailbox directory after standard locations/configuration
checks missed it. User explicitly authorized reuse. The bounded import validates
file ownership/permissions, scope, Google endpoints, current director/private run,
and actual mailbox profile; it copies the grant encrypted into Supabase without
changing source contents. Profile, first durable label intake and subsequent
scheduled worker intakes all executed live. The label is empty, so this establishes
connection/persistence, not finance accuracy. See hosted-hermes-gmail-connection,
hosted-hermes-gmail-intake and hosted-gmail-worker-service evidence JSON files.

The independent finance-worker systemd user service is enabled and active.
It reads vault secrets at startup, polls the explicit finance label, and stops
scheduling a connection after a permanent provider failure. That status update
uses connection CAS so it cannot overwrite a successful concurrent reconnect.
Transient provider errors retain the existing bounded job retry path.

Migration008 adds director-configured1/2 approval policy, version-bound hashes,
stale-proposal invalidation, current-role checks and guarded pre-send claims.
The actual owner browser saved2→1→2; audit actor/version/revision readback verified
both changes, final policy2/version3. No live payment approval or transfer occurred.
The UI and authenticated server route showed the real director scope and connected
Gmail. The first live script incorrectly expected backend-only connection data in
the intentionally redacted browser snapshot; both policy saves had succeeded.
The assertion was corrected and a readback-only browser run passed without
repeating the policy mutations. See hosted-director-policy-browser.json.

Final352Python+10subtests/21webunit/4currentbrowserchecks/build/TypeScript/Ruff pass.
The full-suite first pass had two obsolete wording assertions after the policy
change; fixed expectations/guidance and rerun passed. The bounded import suite
covers unchanged source bytes, wrong mailbox, broad scopes, source permissions,
symlink refusal, removed director and profile failures. Prior Auth fixture runs
remain separately labeled, not live provider checks.

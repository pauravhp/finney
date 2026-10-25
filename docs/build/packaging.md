# Packaging, onboarding and independent integration review

October 24, 2026, Pacific. Packaging builder follow-up. No hosted Supabase,
Google/Gmail, payment, deployment, outreach or account operation was run by this
builder. All SQL integration described below used the documented **loopback local**
PostgreSQL cluster and new disposable test databases.

## Shipped paths

- `app/cli.py`: actual commands doctor/init/migrate/migration-sql/event-sql/worker/
  oauth-server/check-csv. Worker invokes coordinator dispatch_job with scoped
  tools/database, renews leases, preserves blocked outcomes, schedules only
  explicitly retryable failures and stops on authorization failure.
- `app/setup_checks.py`: local source/dependency verification, separate configured
  vs passed/blocked/not_run checks, optional one-shot live REST/model/Jev/authorized
  Gmail profile probes, no PostgreSQL authentication, credential guessing or
  provider fallback/retry.
- `app/onboarding.py` and `skills/onboarding/SKILL.md`: restricted onboarding mode,
  first-model/runtime bootstrap fallback, one measured probe per setup session,
  private local bootstrap receipts, real Supabase progress when verified scope
  exists, no agent-written successful readiness labels.
- `app/event_setup.py`: offline stable-ID event SQL, validating two pre-existing
  Google Auth identities before director/approver memberships. No invented user,
  simulated approver or opening money. Repeated setup preserves the same event.
- `app/setup_sql.py`: offline SQL-editor rendering with the same checksum receipts
  and migration content as the direct runner. Repeats skip matching migrations;
  altered applied checksums stop. Direct migrate uses TLS and one authentication
  attempt; errors never print connection strings/passwords/provider bodies.
- `app/resources.py` and wheel force-includes: both source checkout and installed
  wheel contain/read onboarding and finance skills plus all versioned migrations.
  Runtime owner updated its finance skill path to use the resolver.
- Root README, `.env.example`, `docs/setup/manual.md`: actual clone/bootstrap/start,
  deterministic manual equivalent, provider modes/scopes/callbacks, member vs
  director identity, shared run setup, opening-record semantics, Vercel root/env,
  supervision/recovery, upgrades, backups/restore, export/handover and removal.
- Optional payments extra `x402[evm,httpx]==2.25.0` was requested/approved by
  coordinator and kernel owner; lock updated. It is not a default dependency.

The source-checkout quickstart uses uv's frozen lock; a separate pinned public
Hermes bootstrap creates a clean runtime source/interpreter and does not reuse a
personal profile. Actual Hermes installation/onboarding provider evidence belongs
to `docs/build/runtime.md` and `evidence/runtime-onboarding-live.json`; this
builder did not repeat paid provider calls or treat unit fixtures as live proof.

## Verification and evidence

| Check | Result and scope |
|---|---|
| `uv run --no-sync pytest -q tests/test_packaging.py tests/test_packaging_postgres.py` with explicit loopback FINANCE_TEST_DB_URL | **16 passed**: 14 local unit/dispatch/security tests + 2 actual local SQL tests |
| `uv run --no-sync pytest -q -m 'not live'` with same loopback URL | **101 passed, 6 subtests passed** at final integration snapshot (all three current migrations) |
| Scoped `ruff check` on owned CLI/setup/resource/tests | Passed after import formatting/intentional safe-boundary annotations |
| `uv lock` | Resolved optional exact x402 extra; source default dependencies unchanged |
| `uv build --wheel --out-dir /tmp/director-finance-packaging/dist` | Built wheel with assets |
| New `/tmp/director-finance-packaging/clean` venv, wheel install | Actual isolated install with 35 default packages |
| Wheel resource script outside checkout with sanitized environment | Onboarding skill, runtime finance skill and SQL assets all resolve through `app/assets`; rendered migration SQL available |
| Clean installed `finance init --manual` outside checkout | Exit 0, manual_requested, ready_for_worker false, remote checkpoint pending, protected local receipt exists; no provider calls |
| Web follow-up `npm test`, `npm run typecheck`, `npm run build` | **10 unit tests pass**, typecheck and production build pass, including opening-cash validation |

Local SQL tests apply the receipt-tracked generated schema, repeat it unchanged,
and reject modified applied hashes. The event script rejects missing Google
identities before mutation, then creates one shared event with the intended two
roles and produces no duplicate event on replay using explicit **test-only**
identity fixtures. This proves local SQL behavior, not hosted Google identity or
human approval.

Unit checks prove a configured key cannot mark an unrun/failed check passed; a
401 gets one request and no alternate credentials or SQL login; an agent's
requested verified status cannot override measured failure; bootstrap checkpoint
permissions are 0600; no model key falls back without inference; OAuth server uses
factory/loopback 8767/access_log=False; failed migration uses TLS once and redacts
exception text; worker dispatch preserves scope, retries explicitly retryable
blocked work, and halts auth failures without a second status-write request.

## Failures, repairs and retests

1. Inspection found a substantive old false-readiness path: doctor returned
   ready_for_worker from key presence even after live Supabase failure. Replaced
   it with named measured checks and real readiness conjunction. Regression tests
   cover configured-but-unrun and one failed authorization. Retest passes.
2. Initial Ruff pass flagged import order and broad exception boundaries inherited
   by/needed at safe launcher/job boundaries. Fixed imports; documented safe
   exception boundaries that deliberately print only types/fixed codes, and kept
   lost lease writes from overwriting another worker. Scoped Ruff now passes.
3. Initial wheel inspection would have omitted skills/migrations because only app
   was packaged. Added force-includes and source-or-wheel resource resolution;
   actual built/installed wheel now reads its bundled assets outside the checkout, including all three current SQL migrations.
4. Initial `npm --prefix web exec prettier ...` used paths relative to the wrong
   working directory; no UI code changed. Ran pinned installed Prettier from web
   cwd; typecheck and final build passed.
5. Independent integration review found generic intake instructions were accepted
   by UI but ignored by dispatcher. Replaced that form with actual Gmail sync/CSV
   operations and explicit source payloads. Typecheck and production build pass.

## Integration findings sent to coordinator

Coordinator-owned fixes were requested rather than edited concurrently:

- Callback must recheck active/non-demo run after consent, not just at start.
- Full Gmail sync should resolve an actual label ID and refilter each current
  message's label, matching incremental intake's bounded scope.
- Source revisions must reuse/link the case and invalidate dependent approvals,
  rather than create an unrelated new case.
- Actor report/export tools returning a bare snapshot need explicit prepared/no
  completed effects status; real generate_report already persists its artifact.
- Revoked/failed Gmail authorization should update connection health, instead of
  retaining an old connected badge after a blocked job.
- OAuth backend responses should be no-store and callback no-referrer; never log
  code/state/authorization URLs. Web proxy already returns private/no-store.

Coordinator reported all six fixes landed. The clean installed server smoke also
verified absent-configuration x402/OAuth 503 states and no callback query values in
access logs; coordinator owns live-provider health verification. The worker dispatch and explicit retry
integration are covered by local tests here.

6. The realistic copied-example path was added after reviewing blank optional
   UUID fields, which a no-env-file smoke can miss. Coordinator config now ignores
   empty env values; both unit regression and actual clean installed package with
   copied .env.example pass. CLI Settings construction moved inside the safe error
   boundary so malformed inputs cannot print validation details or traceback.

Final clean-wheel machine-readable evidence:
`docs/build/evidence/packaging-clean-wheel.json`. It includes bundled three-migration
resources, manual not-ready bootstrap, copied-example init exit 0/doctor exit 2,
actual unconfigured `/x402/health`, blocked `/x402/sponsor-report`, blocked OAuth
callback, and absent code/state markers in server logs. The local smoke server was
terminated after verification. No server or external account was left running.

## Successful patterns and process lessons

- Keep SQL-editor and CLI migration receipts identical. A complete manual fallback
  must support later resumption without replaying already-applied CREATE TABLE.
- A clean wheel check must execute outside the checkout; source files can otherwise
  hide missing package assets and turn a broken release into a false pass.
- A configured provider setting and verified operation are different states. Keep
  readiness deterministic and independent of model-written checkpoint labels.
- Store only safe bootstrap progress locally before cloud access. Once scoped
  Supabase is verified, persist real progress there and keep failed durability
  explicit; local state is not a fallback financial database.
- On auth failure stop, preserve the error type, and ask the owner to confirm exact
  configuration/IP-ban state. Never guess URI formats, switch usernames or retry
  in loops. This follows `INCIDENT-001-database-auth.md`; this builder made no
  hosted connection attempt during or after that hold.
- Test legitimate request/dispatch paths along with denied paths. An API can
  reject attackers correctly while still rejecting every real user action.
- Name UI controls after the actual dispatcher effect; accepting a field that is
  ignored is a functional defect even if the job itself returns completed.

## Unverified external gates

No successful Google SSO/Gmail consent or app ingestion was claimed here; Google
client/provider setup remains owner work. Hosted Realtime recovery, private
Storage write/read, actual two-human payment approval, wallet/testnet execution,
and end-to-end improvement must be checked using real scoped provider evidence.
The clean wheel has no credentials and correctly remains not ready. No Vercel
public deployment was performed. First-time organizer setup duration/manual-step
counts and a separate-project backup restore have not been measured.


## Final autonomy follow-up

Added `app/scheduler.py` and background-only worker integration. Discovery runs
at startup and on a monotonic 60-second cadence, with a configurable bounded
round-robin batch (default 20, maximum 100) and a 20-second per-tick deadline to
preserve worker lease renewal. No web scheduling timer or unrelated scheduled
financial effect was added. `--once` does not construct/query the scheduler.
`--no-auto-intake` or FINANCE_AUTO_INTAKE_ENABLED=false disables discovery;
already-queued jobs still run.

A candidate needs a connected Gmail connection, a well-scoped explicit label,
active nonexpired non-demo run, an active director membership matching the
connection's persisted connected_by, and matching private token metadata. The
scheduler never reads encrypted_token or calls Gmail. It queues `{source:gmail}`
with that actual recorded director as requested_by, leaves the label on the
connection, skips pending/running intake, and uses connection+UTC-minute
idempotency. A 409 counts as a race only after verifying the existing exact job;
other actor/payload conflicts are not success. Authorization errors stop the
worker without another status-write attempt. The connector independently checks
current authority before using the token.

Verification: `tests/test_scheduler.py` plus packaging tests: **39 passed**.
Latest complete loopback-local Python suite: **152 passed, 10 subtests passed**.
Scoped Ruff passed. New tests cover the positive director path, absent/revoked/
wrong-scope authority, expired/demo runs, absent scoped token, broad/missing label,
pending intake, cadence, restart/concurrent idempotency, bounded pagination,
disabled/background startup, once-mode isolation and first-auth-failure stop.
These are explicit database fixtures and local SQL tests; no Gmail/provider call
or live automatic-mail claim was made.

Rebuilt wheel now contains `app/scheduler.py` and **all five** source migrations,
verified by actual zip inspection. Existing outside-checkout clean-install proof
is retained separately in packaging-clean-wheel.json; the final-wheel receipt
records the new five-migration artifact. Main README explicitly states Gmail
attachment metadata/references only, with no PDF/OCR/receipt-file parsing claim.
The Learning UI default now uses organizer-expenses-blockers-v4 and documents
finance-evaluator-v2. No additional model call was attempted. Personal Hermes
configuration/profile was untouched. Coordinator will perform final independent
suite/browser/build checks after this freeze.

The first scheduler lint pass flagged an unnecessary Z-to-offset substitution;
Python 3.11+ accepts ISO Z directly. Removed it and reran scoped Ruff successfully.

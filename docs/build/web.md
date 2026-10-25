# Finance web build evidence

Updated October 24, 2026, 7:26 PM America/Vancouver (2026-10-25 02:26 UTC).
Owner: web builder. Scope: `apps/director-finance/web/` and this record only.
No deployment, external account creation, mailbox intake, money transfer, or
commit was performed by this builder.

## Implemented surface and authority

Next.js 16.4.3 / React 19.3.1, pinned lockfile, locally bundled DM Sans Variable,
responsive operations layout with original luminous star/lilac direction.
Impeccable context/init/new-work/craft-floor were read and the detector ran once
with `[]` findings. The user pinned the visual direction and deferred full
polish/interviews; no alternate-world interview or extra agents were introduced.
`web/PRODUCT.md` and `web/DESIGN.md` record the supplied brief and built system.

Screens: overview; cases/source versions/private artifacts; obligations;
exact-action proposals and human decisions; persisted activity; sanitized
observed diagnoses; actual baseline/candidate procedure diff; private procedure
artifacts; per-case evaluation, overhead and control results; promotion/rollback;
actual report snapshots/private downloads; provider/worker health.
No application module imports test fixtures. Missing balances stay **Unknown**.
No default successful activity, evaluation gain, payment, or provider connection
is seeded. Acknowledged jobs say **queued**, not complete.

Auth uses `@supabase/ssr` and Google `openid email profile` only. Auth is verified
with `getUser` per protected endpoint; the proxy refreshes cookies with
`getClaims`. The director separately grants Gmail for a shared event run.
Other members never request Gmail scopes. No service-role key exists in web code
or the app's environment contract.

## Route/data contract

| Route | Authoritative operation |
|---|---|
| `GET /api/finance/scopes` | Authenticated user's active memberships, organizations and RLS-readable runs |
| `GET /api/finance/snapshot?organization_id=&run_id=` | `get_finance_snapshot`; schema and returned scope validated |
| `POST /api/finance/commands` | `enqueue_finance_command`; six allowed command types, stable idempotency key |
| `POST /api/finance/approvals` | Reads proposal in selected run, preserves exact returned hash, then `approve_finance_proposal` |
| `POST /api/finance/demo` | `create_finance_demo`; optional specific previous owner run, never global reset |
| `POST /api/connectors/gmail/start` | Fixed server-configured backend, verified user JWT; backend enforces director/non-demo scope |
| `GET /auth/callback` | Google basic-identity PKCE code exchange, fixed same-origin destination |
| `POST /auth/signout` | Clear current authenticated session |

Mutation routes require matching HTTP origin and JSON bodies. Caller-supplied
roles/actor identities are rejected. Database controls recheck authority and
versions; UI role gating is not relied upon for security. The app never writes
financial rows, payment state, or approval counts directly.

Snapshot matches `docs/build/kernel.md`: money position/obligation values are
integer decimal strings/null, formatted via BigInt without Number conversion.
The kernel also normalizes action/report money recursively. JSON numbers are
rejected for position/obligation money. Reports and source/procedure artifacts
use authenticated `finance-artifacts` Storage downloads under the selected run
prefix. Private URLs are not generated or stored. Generic raw inspection redacts
credential/OAuth URL fields while retaining token-count metrics.

Private channel `finance:<organization_id>:<run_id>` listens for `state_changed`.
It refetches on notification and subscribed/reconnected status; a 30-second poll
recovers missed changes. Scope changes clear previous records and request sequence
checks reject stale cross-run responses. Subscription status, stale state, worker
heartbeat, errors and missing setup are explicit. This subscription code has not
yet been verified against a hosted Supabase project.

Learning evaluation submits an actual `actor_completed` trace UUID and trusted
suite key (`organizer-expenses-blockers-v4` default, with the current
`finance-evaluator-v2` contract). UI labels that suite's inputs
as synthetic test-organization cases and does not label replay as settlement.
Promotion is shown from persisted gate evidence; there is no browser promotion or
financial-control bypass. The runtime remains responsible for generating changes
and enforcing evaluation/promotion.

## Validation evidence

All commands ran from `apps/director-finance/web` on October 24 Pacific.

| Command/check | Result | Verification level |
|---|---|---|
| `npm install` then final `npm audit` | Final zero vulnerabilities | Dependency audit |
| `npm test` | 9 passing contract/security/precision tests | Unit only; fixture explicitly labeled, not imported by app |
| `npm run typecheck` | Passed | TypeScript |
| `npm run build` | Passed; all app/API/auth routes emitted | Local production build |
| `npm run test:browser` | 4 passing (desktop/mobile) | Local Chromium, production server, **unconfigured providers** |
| `node .../impeccable/scripts/detect.mjs --json src` | `[]` | Mechanical UI detector |
| Batched screenshots | Desktop/mobile overview and connections inspected; one confirmation mobile inspection | Local visual/accessibility check |

Unit evidence covers >2^53 minor amounts, negative subunit amounts, USD/JPY/KWD,
unknown-vs-zero, numeric-money rejection, cross-run snapshot rejection, caller-role
and actor rejection, unsupported mutations, specific-run reset schema, unsafe
source URLs, credential-field inspection redaction and Google redirect origin.
Browser evidence covers empty/setup states, disabled unavailable commands,
no fabricated zero balance, Learning/Approvals/Connections navigation, no page
errors or horizontal overflow at 1440x1100 and 390x844, foreign-origin rejection,
valid-origin unconfigured rejection, malformed scope and safe callback redirect.

Screenshots: `web/test-results/{desktop,mobile}-{overview,connections}.png`.
They are local, ignored acceptance artifacts showing **unconfigured** state.
They do not demonstrate a live financial integration. Root can reproduce them
with `npm run build && npm run test:browser`.

## Failures, causes, fixes and retests

1. First TypeScript run failed on generic evidence-record property access,
   overloaded SSR browser-client return types leaking `any`, and unknown values
   used as JSX conditions. Explicit record/client types and boolean conditions
   fixed these; later typechecks and production builds passed.
2. Initial dependency audit: Zod 4.3.6 had a high-severity constrained-collection
   issue; tsx's esbuild had a low-severity Windows dev-server issue. Updated pinned
   Zod to 4.6.7 and tsx to 4.23.15; final full npm audit reports zero vulnerabilities.
   `npm audit fix` alone did not fix the old tsx transitive pin; upgrading its
   direct owner did. No force upgrade was used.
3. Initial browser run had four failures. Two were a test assumption: four cash
   amounts display `Unknown`; the status badge's actual text is lowercase. The
   assertion now checks the four amount values. Two revealed Next's local
   request URL normalized to `localhost` while actual browser Host was
   `127.0.0.1`: callbacks changed authority, and valid same-origin mutations would
   be rejected. Callback/CSRF origin now use actual HTTP Host, never an untrusted
   forwarded-host override. Added positive same-origin mutation and callback
   authority checks. Retest: four passing tests across both viewports.
4. First mobile connections screenshot captured the drawer mid-close. Closed
   mobile navigation now becomes CSS-hidden (also removing keyboard access), and
   the browser check waits until hidden. Confirmation screenshot is settled.
5. Impeccable concept seed initially refused missing PRODUCT.md. Wrote the supplied
   confirmed product record in the owned web package, reran successfully (seed
   24acec9d). The pinned user direction takes precedence over the roll.
6. Two read/helper commands failed harmlessly: assumed migration filename was
   wrong (fixed by `rg --files`); `python` alias was absent (used `python3`). No
   application/provider state was affected. Lesson: discover exact paths and use
   declared runtimes rather than shell aliases.

## Successful patterns and lessons

- Coordinate snapshot shape before UI semantics. Null amounts, exact action hash,
  sanitized traces and exact eval row fields avoided invented client-side rules.
- Verify a positive same-origin request as well as a blocked foreign origin.
  Negative-only CSRF tests would have missed a broken legitimate action path.
- Keep command idempotency keys after an ambiguous request failure; discard only
  after the queue acknowledges. Retrying identical work can recover its actual job.
- Keep raw provider artifacts private and render procedure text as escaped text.
  Use Blob downloads, no persistent public/signed URL in records or logs.
- Avoid broad token redaction that hides usage metrics: protect access credentials,
  preserve prompt/completion token counts needed for evaluation overhead.
- Distinguish owner-only demo isolation from shared event authority. The UI states
  two-person payments require a shared run; it never simulates another approver.
- A fixed no-provider production build gives useful browser regression coverage
  while clearly leaving provider acceptance pending.

## Remaining gates

No hosted Supabase project/Auth session was available to this builder. Actual
Google SSO, RLS cross-user access, private Realtime reconnect recovery, worker-to-
browser updates, private Storage reads/downloads, and two-person shared-run
approval still require real integration verification. The private demo design
intentionally does not let a second identity into an owner's run; use an actual
shared event run for two-human approval testing.

The new Gmail start proxy is wired but needs FINANCE_API_URL, backend Google OAuth
configuration and real director consent. GOOGLE_REDIRECT_URI points to the backend
callback, separate from web SSO callback; an optional web callback proxy was not
added. No personal mailbox is connected to anonymous/personal demo state and no
broad inbox import is requested by the UI.

Vercel root/build/environment and callback setup are documented in `web/README.md`.
No Vercel deployment was attempted (not authorized). Live Hermes/Jev/Gmail/model/
testnet/evaluation evidence belongs to coordinator/provider acceptance; local UI
or unit passes do not satisfy those gates.

## Coordinator integration follow-up

October 24 Pacific: added a director-only opening-cash form for shared runs with
unknown cash. It uses exact BigInt decimal-to-minor conversion, accepts zero,
fixes currency to the selected run, requires a Pacific date/source note/explicit
attestation, and queues `intake` with `source: opening_snapshot` and
`attested: true`. It labels owner attestation distinctly from bank confirmation;
the kernel remains responsible for once-only balanced posting and actor authority.
Form validation covers >2^53 units, zero, invalid precision/negative/nonfinite/
exponential/overflow values, invalid dates, absent note and unchecked attestation.
Web unit suite is now **10 passing**, typecheck and final production build pass.
No hosted opening snapshot was executed by this builder.

Independent review found the original generic intake instruction was ignored by
the integrated dispatcher. The UI now names the real operation: **Add source
records**, with explicit connected Gmail finance-label sync or pasted CSV import
using the run's fixed currency. It no longer offers a free-text request that the
backend does not execute. CSV rows remain reported evidence and do not establish
opening cash by themselves. Typecheck and production build pass after this change.

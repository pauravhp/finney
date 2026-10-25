# Finney

An event-owned finance agent for hackathon directors. It keeps source evidence,
budget commitments, decisions, reports, and evaluated procedures together in
Supabase, with a Next.js browser workspace. Hermes performs scoped agent work;
Jev reviews actual traces. Payment support uses Coinbase Wallet MCP and Base
Sepolia test funds, with exact-action human approvals and receipt verification.

The app never substitutes a fake successful Gmail intake, payment, model call,
or improvement. Missing access is visible as blocked. See
[validation and current limits](docs/VALIDATION.md) for what has actually been
verified, and [deployment](docs/DEPLOYMENT.md) for the dashboard/worker split.

## Start here

Use Linux or macOS, Python **3.11–3.13**, Git, [uv](https://docs.astral.sh/uv/getting-started/installation/),
Node **22+**, and npm. You need an event-owned Supabase project and funded model
access; Gmail and payment consent are separate setup steps. Cloud providers and
inference can cost money. No service is purchased, account created, or site
published by these setup commands.

Clone [Finney](https://github.com/pauravhp/finney), then work from the repository root:

```sh
git clone https://github.com/pauravhp/finney.git
cd finney
uv sync --frozen --extra dev
cp .env.example .env
chmod 600 .env
uv run --frozen python -m app.runtime.bootstrap --install
uv run --frozen finance init
```

Put the actor model settings in `.env` privately before expecting agent guidance.
Without model access, `finance init` prints the exact bootstrap/manual next step
without calling inference. Without the pinned runtime it prints the runtime
bootstrap step. Once both work, `finance init` runs the restricted onboarding
agent, checks the current state, and explains the next incomplete step. Rerun it
after each owner action. It cannot log in, consent, purchase, or deploy for you.

For the deterministic manual path, use `uv run --frozen finance init --manual` and
the steps below. A configuration flag means a value is present; **passed** means
the named check actually ran. An untested provider remains **not_run**.

## Manual setup

1. **Choose model access.** In the protected root `.env`, set the actor's
   `FINANCE_MODEL`, `FINANCE_MODEL_BASE_URL`, `FINANCE_MODEL_API_MODE`, and
   `FINANCE_MODEL_API_KEY`. Supported transports are native Anthropic Messages
   (`anthropic_messages`, HTTPS base such as `https://api.anthropic.com/v1`) and an
   HTTPS provider supporting OpenAI-style Chat Completions (`chat_completions`,
   provider's exact base ending before `/chat/completions`). Use a model actually
   enabled on that provider. There is no automatic provider or key fallback.
   The example uses the configured Claude Sonnet model; change it for your account.

2. **Install the pinned runtime.** Run the bootstrap command above. It fetches the
   exact public Hermes revision in `app/runtime/hermes-lock.json`, verifies the
   entire clean source tree, and installs frozen dependencies in
   `.runtime/hermes-venv`. It does not copy personal Hermes memories, profiles,
   plugins or dotenv files. Repeating the command verifies/resumes installation.
   The actor defaults to that isolated interpreter. Set absolute
   `FINANCE_HERMES_SOURCE` and `FINANCE_HERMES_PYTHON` only for an explicitly
   selected equivalent installation matching the pin.

3. **Connect Supabase.** Use one dedicated project owned by the event. Put its
   `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, and server-only `SUPABASE_SECRET_KEY`
   in the root environment. Prefer the current `sb_secret_...` key; the legacy
   `SUPABASE_SERVICE_ROLE_KEY` is an explicit compatibility fallback. Never put a
   backend secret in `web/.env.local`, a browser bundle, source control, or chat.

4. **Apply migrations once with receipts.** The SQL-editor path needs no direct
   database login:

   ```sh
   uv run --frozen finance migration-sql > finance-setup.sql
   ```

   Review that file and execute it in the event project's Supabase SQL editor.
   It contains the versioned schema plus checksum receipts, and safely skips
   already-applied matching migrations. The file contains no credentials. For
   direct administration, copy the **exact Session pooler URI** from Supabase's
   Connect dialog into `SUPABASE_DB_URL`, privately, then run:

   ```sh
   uv run --frozen finance migrate
   ```

   This uses TLS, advisory locking, transactions and the same receipts. It makes
   no alternate-host/user/password guesses and does not retry authentication.
   **Stop on the first authentication failure.** Confirm the exact URI and any
   IP-ban state with the owner dashboard before another attempt. `doctor` and
   `init` never authenticate directly to PostgreSQL. Do not apply the raw schema
   manually and then claim a receipt exists; use one of these receipt-tracked paths.

5. **Set up the browser with Supabase email/password sign-in.** In `web/`:

   ```sh
   npm ci
   cp .env.example .env.local
   npm run dev
   ```

   Set only the public Supabase URL/publishable key in `web/.env.local`. Email
   authentication is enabled by default in Supabase; no Google SSO client is
   required. Open [the local workspace](http://127.0.0.1:3000), create an account
   and confirm its email if required, then sign in with email/password. In
   Supabase URL Configuration, set the actual dashboard Site URL and allow its
   `/auth/callback` (local: `http://127.0.0.1:3000/auth/callback`; add the actual
   Vercel origin after deployment).

   For the first private demo, the project owner can create the director's actual
   password account under Supabase Authentication → Users, with confirmed email,
   so sign-in does not depend on delivering a confirmation message. Public signup
   confirmation/recovery needs working email delivery; Supabase's default sender
   is limited to project-team addresses. Do not disable verification or fabricate
   a second human to make the demo pass. See [auth setup](docs/AUTH_SETUP.md).

6. **Create the private event with the real director.** Sign in with the
   director's confirmed email/password account and copy its UUID from Supabase
   Auth Users. From the application root, replacing the explicit values:

   ```sh
   uv run --frozen finance event-sql --name "My Hackathon" --director-user-id DIRECTOR_UUID --currency USD > event-setup.sql
   ```

   Review and execute that SQL in the owner project. It checks the existing
   confirmed email/password identity, creates the director membership and a
   durable private event run (`is_demo=false`), and prints the organization/run
   IDs plus `approver_configured=false`. Copy those IDs to
   `FINANCE_ORGANIZATION_ID` and `FINANCE_RUN_ID` for scoped administration. Rerun
   the same command safely; IDs persist in the protected bootstrap plan.
   If a distinct real approver is ready during initial setup, include
   `--approver-user-id APPROVER_UUID` to validate and add their account too.
   Adding an approver later needs an explicit membership change; changing an
   existing bootstrap plan is rejected. A director alone can connect Gmail and
   inspect finances. In Approvals, the director selects one-director approval or
   two-person approval (the default). Policy changes invalidate pending approvals
   and are blocked while a payment remains unsettled. In two-person mode the
   approvers must be distinct actual eligible people; never invent a second user.
   The event owns its finances; the app creates
   no opening money from this setup. In Overview, the director can choose **Set
   opening cash**, enter the exact amount/date/source note and attest it. Zero is
   valid. The service records it once as **owner-attested**, separately from bank
   confirmation; importing a CSV alone does not establish ledger cash.

7. **Connect the director's Gmail through isolated Hermes.** The default is
   `FINANCE_GMAIL_BACKEND=hermes`. The runtime bootstrap above installs the pinned
   Google dependencies into this app's `.runtime/hermes-venv`. Personal Hermes
   configuration, profiles and plugins are never modified or automatically loaded.
   An explicitly authorized readonly grant can be imported using the separate
   command below; this never edits the source integration.

   Generate a token-encryption key locally, then store it privately as
   `FINANCE_TOKEN_ENCRYPTION_KEY` (keep it with the owner's protected backups):

   ```sh
   uv run --frozen python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
   ```

   In Google Cloud, enable **Gmail API** and create an OAuth **Desktop app** client
   named “Finney mailbox”. Dashboard email/password sign-in needs no Google client. Download the Desktop client JSON to a private file
   outside the repository and add the director as a test user if the Google app
   is in testing. Only `https://www.googleapis.com/auth/gmail.readonly` is requested.
   See [mailbox setup](docs/AUTH_SETUP.md#hermes-gmail) for the separate Gmail grant.

   Create Gmail label `director-finance` and add only intended finance messages.
   Keep `FINANCE_GMAIL_QUERY=label:director-finance`. After step 6, with the
   Supabase, encryption-key and shared-event settings loaded on the worker host:

   ```sh
   uv run --frozen finance gmail-connect --client-file /private/path/mailbox-client.json --director-user-id DIRECTOR_UUID
   ```

   Open the returned Google authorization URL, approve the director's mailbox,
   then copy the **full** final `http://localhost:1/?...` URL from the address bar.
   The localhost page failing to load is expected in this upstream Hermes flow.
   Within ten minutes run:

   ```sh
   uv run --frozen finance gmail-connect --complete
   ```

   Paste that URL into the hidden terminal prompt. Do not paste it into chat or
   put it in command arguments. The command consumes the pending authorization
   once, checks director authority and the private event again, verifies the real
   mailbox profile, then atomically stores encrypted credentials and connection
   metadata in Supabase. Pending authorization state is also encrypted there.
   Credentials exist in a private temporary Hermes profile only during each call;
   ordinary team members never connect a mailbox. A failed exchange requires a
   fresh start; the app never guesses credentials or retries authentication.

   Return to Connections to inspect the recorded status. Gmail reads now run
   through the pinned Hermes Workspace integration, with existing pagination,
   duplicate protection, source evidence and review-job persistence. Gmail grants
   allow mailbox reads; **label restriction is enforced by this application**, not
   by a label-specific Google OAuth scope. Allowed attachments are downloaded
   within per-message/batch limits, stored privately and extracted before review
   is queued. PDF text extraction runs in a bounded subprocess; configured Claude
   vision handles small scanned PDFs and receipt images. OCR remains unverified
   evidence. Unsupported or incomplete attachments stay visibly unresolved.
   See [document intake](docs/DOCUMENT_INTAKE.md) for exact limits and failure states.

   **Already authorized Google elsewhere?** Explicitly reuse an existing
   owner-private authorized-user JSON grant with exactly Gmail readonly scope:

   ```sh
   uv run --frozen finance gmail-connect --import-token-file /private/path/google_token.json --expected-mailbox director@example.org --director-user-id DIRECTOR_UUID
   ```

   This verifies the actual mailbox through isolated Hermes, then saves an
   encrypted app grant in Supabase. The source profile/file is never changed.
   No automatic credential search occurs; use this only for a grant the owner
   explicitly authorized reusing. Broader scopes are rejected.

   The previous browser OAuth connector remains an explicit alternative under
   `FINANCE_GMAIL_BACKEND=api`; see [legacy setup](docs/AUTH_SETUP.md#legacy-browser-mailbox-route).
   It is not needed for the default Hermes mailbox route.

8. **Connect Jev separately.** Put the event's Vercel AI Gateway credential in
   `AI_GATEWAY_API_KEY`. Jev uses the Typesafe decision endpoint via Gateway,
   separate from the generative model's transport/key. Its scores are triage,
   not proof of correct finances or improvement.

9. **Verify, then launch.** From the root:

   ```sh
   uv run --frozen finance doctor
   uv run --frozen finance doctor --live
   uv run --frozen finance worker
   ```

   `doctor` checks local/runtime configuration without provider calls; exit 2
   means readiness is not verified. `--live` makes at most one probe per configured
   service: read-only REST/schema/private-bucket checks, small real model/Jev
   requests, and an authorized Gmail credentials/profile check. It imports no
   messages, makes no payment, and does not log into PostgreSQL. Model probes can
   incur a small charge. A failed probe remains blocked; entered keys never pass
   a provider check. The worker is foreground and uses durable Supabase jobs.
   Background mode discovers connected Gmail work at startup and on a 60-second
   cadence. Each tick scans at most 20 connections (configurable, max 100),
   rotating through larger sets. It queues intake only for active nonexpired
   shared runs whose recorded mailbox connector still has an active director;
   existing queued/running intake is skipped. The scheduler never calls Gmail or
   reads/decrypts tokens itself. The actual intake uses each connection's existing
   finance label and rechecks director authority before using its token.

   Set `FINANCE_AUTO_INTAKE_ENABLED=false` or run
   `uv run --frozen finance worker --no-auto-intake` to disable discovery while
   processing already-queued work. `FINANCE_AUTO_INTAKE_BATCH_SIZE` controls the
   bounded per-tick scan. `finance worker --once` never discovers or creates
   background jobs: it handles one existing job, or exits if none is queued.

   On the dashboard, you can also queue intake for the configured finance label. The first
   real job associates the worker with the run; source versions, cases, reviews
   and activity appear from persisted records. Generate a report and inspect its
   private artifact. Confirm actual email/password sign-in, private Storage write/read,
   Realtime recovery and the configured human-approval policy independently; doctor names its
   narrower verification limits. A visible empty workspace is not a live-flow pass.

## Working with Finney

Use **Work with Finney** to ask a question, enter an expense or expected income,
or upload a PDF/text/CSV/receipt image. Submitted work is queued; the worker stores
the evidence, runs the actual actor and persists its source-linked finding.
The form supports files up to 3 MiB. Original documents and extracted text remain
in private Supabase Storage. Unknown, malformed and incomplete evidence stays
visible rather than disappearing from the case.

The budget register separates allocations from cash. Finney or a finance member
can propose a new allocation; a director explicitly approves it. Existing
commitments constrain reductions. When budgets are configured, unassigned or
overcommitted payables block payment preparation. Opening cash, reported receipts,
promised sponsorship and actual settlement are distinct records.

Generate a close report to persist exact totals by currency, commitments,
source references, approvals, unresolved cases and handover notes. The report
states whether reconciliation is recorded. It does not file taxes or infer a
complete bank history from email. Review disclosures before sharing with a sponsor.

Eligible completed expense reviews automatically queue a bounded diagnosis. Jev
triage and a generative reviewer inspect the real trace; a supported procedure
defect can produce a versioned candidate. Baseline and candidate use identical
frozen context on validation, regression and untouched transfer cases. A separate
SQL gate requires measured gain and retained controls before activation. Rejected
diagnoses and candidates remain recorded; running the loop is not proof of gain.
See [runtime skills](docs/RUNTIME_SKILLS.md) and
[learning experiment requirements](docs/build/LEARNING_EXPERIMENT.md).

Each private event starts with 1,000 reserved model calls and three improvement
attempts. A director can explicitly raise limits via `set_finance_execution_limits`;
consumed reservations are never erased. Demo runs have lower allowances shared
across resets, plus a service-wide daily ceiling. OCR reserves a call too.
These are conservative call limits, not exact dollar budgets.

Creating a demo seeds two explicitly synthetic source cases and queues actual
reviews. It never seeds an answer, approval, payment or successful improvement.
Demo state is isolated by owner/run and cannot access a shared wallet or personal
Gmail grant. Public anonymous signup and anti-abuse setup remain deployment tasks;
the current dashboard uses an authenticated director account.

## Optional testnet payments

Install the optional extra only when you intend to configure it:

```sh
uv sync --frozen --extra dev --extra payments
```

Run `finance coinbase-connect --director-user-id DIRECTOR_UUID`, authorize the
existing Coinbase Wallet at its returned URL, then run
`finance coinbase-connect --complete` and paste the full loopback callback in the
hidden terminal prompt. The grant is encrypted in Supabase; personal Hermes and
other applications' credentials are not changed. Run
`finance coinbase-connect --inspect` to read wallet addresses, then set the verified
`COINBASE_SENDER_ADDRESS`. The optional `COINBASE_MCP_TOKEN` is legacy configuration,
not a required manual extraction step. See [Coinbase setup](docs/COINBASE_SETUP.md).
Use `BASE_SEPOLIA_RPC_URL`, network `eip155:84532`, and
`FINANCE_TESTNET_ONLY=true`. The default maximum is 100,000,000 test-USDC base
units; amounts are exact integer base/minor units. No mainnet execution is
implemented by this package.

The current event policy requires either one director or two distinct eligible
humans to approve the exact destination/asset/network/amount/hash before the trusted
executor can request a Wallet MCP send. A sole director can approve their own
proposal only in one-director mode. Agents cannot change the policy, supply human
approvals, or reuse approvals from an older policy version. The
wallet's additional human confirmation is separate from those application
approvals; they are not cryptographic multisig. An uncertain submission is
investigated, never blindly resent. A facilitator or wallet report is not final
cash: actual chain receipt verification is required. Missing wallet consent,
test funds or receipt evidence remains blocked. See
[the implemented Coinbase boundary](adapters/coinbase/README.md) and
[the payment build evidence](docs/build/payments.md).

The OAuth/backend server also mounts an optional x402 resource at
`/x402/sponsor-report`. Set `X402_PAY_TO_ADDRESS`, `X402_PRICE_BASE_UNITS` and the
explicit event scope, and install the payments extra. `/x402/health` reports the
actual configuration state; missing receiver/scope produces a blocked 503 resource.
The shipped resource is the fixed, intentionally public
`testnet-supporter-report-v1` package. It contains no private director snapshot,
receipt, or trace. A payer's actual x402 authorization and chain settlement are
required; the service records reported settlement, verifies the receipt independently,
and queues capped reconciliation while confirmations are pending. No endpoint is
published merely by starting the default loopback server.

## Hosting the dashboard

Local UI is for iteration. For the intended Vercel dashboard, the owner selects
`web` as the Next.js project root, `npm ci` install and `npm run build` build
command. Add the public Supabase URL/publishable key and configure Supabase's
Site URL and `/auth/callback` redirect. Set server-only `FINANCE_API_URL` only if
using the optional hosted mailbox callback backend. Disable public Supabase
Realtime channels; the app subscribes to
private `finance:<organization_id>:<run_id>` channels under the migration's policy.
Keep the durable worker/backend supervised on the chosen host, with its server
credentials there. Follow [deployment](docs/DEPLOYMENT.md) for the full sequence.
Public Vercel deployment remains unverified.

## Checks and troubleshooting

```sh
uv run --frozen pytest -m 'not live'
uv run --frozen ruff check app/cli.py app/onboarding.py app/setup_checks.py app/event_setup.py app/setup_sql.py app/resources.py
cd web
npm test
npm run typecheck
npm run build
npm run test:browser
```

The browser suite checks an **unconfigured** production build; run it before adding
live web `.env.local` values, or use a clean separate checkout. Its local Chromium
path can be changed with `PLAYWRIGHT_CHROMIUM_EXECUTABLE`. Unit HTTP fixtures and
local PostgreSQL tests are not live provider proof. CI runs these checks against
an ephemeral PostgreSQL 16 service with no provider credentials. For local SQL
coverage, set `FINANCE_TEST_DB_URL` to an isolated loopback PostgreSQL admin URI;
the fixtures create/drop random test databases. Never use an operating database.
See [validation and current limits](docs/VALIDATION.md),
[web evidence](docs/build/web.md) and [packaging evidence](docs/build/packaging.md).

- **Runtime hash mismatch:** do not edit or install a personal runtime over the
  verified source. Keep diagnostic evidence, select a fresh source/environment
  path explicitly, and run the pinned bootstrap. Do not weaken the expected hash.
- **Model/Gateway blocked:** check the configured provider's exact model/base/mode
  and enabled balance. Actor and Jev keys are separate. There is no fallback.
- **Database authentication failure:** stop immediately. Confirm the exact
  owner-supplied connection string, permissions, password and IP-ban state in the
  dashboard. Do not try formatting guesses or loops. The SQL-editor path avoids
  a direct PostgreSQL connection.
- **Sign-in fails:** check the account email/password and confirmation status.
  A pending confirmation is not an active session. If email delivery is unavailable,
  the project owner can provision confirmed accounts for actual demo participants.
  Dashboard sign-in and the director's Google mailbox consent remain separate.
- **Worker offline/unknown:** inspect actual process status and recorded jobs.
  A run with no assigned job can have unknown worker status. Never reset an
  uncertain payment to make it appear ready.
- **Checkpoint pending:** before Supabase is reachable, `.state/onboarding.json`
  is a private bootstrap receipt, not a financial database. Once verified scope
  is available, actual progress persists in Supabase; failed remote persistence
  stays explicit. Resume always rechecks actual state.

For opening CSV records, supervision, upgrades, backup/restore, exports, handover
and removal, use [the operating reference](docs/setup/manual.md). The primary
provider references are [Supabase connection setup](https://supabase.com/docs/guides/database/connecting-to-postgres),
[Supabase password auth](https://supabase.com/docs/guides/auth/passwords),
[Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes), and
[uv locked installation](https://docs.astral.sh/uv/concepts/projects/sync/).

This repository contains the standalone application. Private project research,
provider receipts and runtime state are excluded from the public distribution.

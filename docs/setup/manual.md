# Manual setup and operating reference

The root README contains the complete ordered setup path. These are additional
operating details for event owners; no account creation/deployment is automated.

## Identity, authority and handover

Use one event-owned Supabase project and cloud billing owner. Have the director
and a second real person each sign in with email/password. In Supabase's Auth
Users view copy their actual user UUIDs; `finance event-sql` verifies their existing
confirmed, nonanonymous email/password identities before creating shared memberships. It never creates a pretend
approver. Keep director and deputy identities current when student teams change.
Remove old members explicitly in memberships, and revoke old dashboard sessions.
Only directors connect/replace the shared event Gmail grant. An MLH affiliation
is not spending authority or a fiscal-host policy.

### Optional guest demo entry

Guest entry is off by default. To expose it on a controlled demo deployment, set
`NEXT_PUBLIC_FINANCE_GUEST_DEMO=true` in the web app environment and rebuild.
In the event's Supabase Auth settings, enable anonymous sign-ins and configure
the project's anti-abuse controls, including signup verification/CAPTCHA and
request rate limits, before allowing public visitors. The app uses Supabase's
real anonymous Auth session; it does not create a password account or bypass a
CAPTCHA challenge. This entry currently has no CAPTCHA widget or token flow, so
a project requiring a challenge stops with a setup error; add the real challenge
integration before enabling that configuration for visitors.

The guest session can create only its own isolated demo run through the existing
authenticated `POST /api/finance/demo` route. That route queues the actual
labeled synthetic source bundle for worker review. It does not add shared-event
membership, Gmail access, payment access, or a pre-recorded result. Existing
owner-lifetime and service-daily model-call limits continue to apply across
resets. Keep guest entry off until the host has verified anonymous Auth,
anti-abuse controls, cookie/site URLs, demo limits, and worker health in the
target environment.

`finance event-sql` stores a temporary local ID plan in `.state/event-plan.json`
with mode 0600. Rerunning the same command prints identical SQL; changing its
identities/name requires an explicit new `--plan-path`. After execution the real
organization/run/membership records live in Supabase. The plan is not an
alternative financial database. Personal demo runs remain owner-only and expire;
they cannot host a second person's payment approval.

## Opening records and intake

Create only the dedicated finance label selected by FINANCE_GMAIL_QUERY and add
the explicitly intended messages/test thread. Gmail readonly consent grants API
read scope; the application enforces the narrower label for ingestion. Revoking
the grant in Google stops subsequent reads. No mail-send endpoint is exposed.

An opening CSV/statement file has UTF-8 header:

```csv
reference,date,description,amount,kind
opening-1,2026-10-24,Opening cash balance,1000.00,opening_balance
```

Supported kinds are opening_balance, expense, receivable, commitment, and payment.
Imported rows remain reported evidence; a validated file has **not** been persisted. Use `finance check-csv
PATH --currency USD` to validate. To persist an authorized CSV, queue an intake
command with payload `{ "source": "csv", "currency": "USD", "content": "<CSV text>" }`
through the protected authenticated command endpoint. The endpoint's full request
requires organization_id/run_id, command_type=`intake`, payload, and a unique
idempotency_key. Do not call table writes directly from the browser.

Initial intake preserves source versions, records cases and queues reviews. A
receipt is reported evidence; it is not proof the event, vendor or organizer has
received money. Establish/reconcile cash through the event's approved source
process. Review local school/student-union/fiscal-host rules with their actual
sources; ambiguous tax/legal questions remain escalated.

## Worker supervision and recovery

`finance worker` is a foreground process. Use your host's process supervisor to
restart it after host failures; do not call it a hosted reliability guarantee.
Background mode checks connected Gmail metadata at startup and on a 60-second
cadence, with a bounded round-robin batch (`FINANCE_AUTO_INTAKE_BATCH_SIZE`, default
20). It queues only active shared runs with a still-active director recorded on
the connection and a scoped private token record. It never requests messages or
token contents itself; actual intake preserves the connection's label and checks
authority again. Existing queued/running intake is skipped and a connection/minute
idempotency key handles duplicate scheduler processes/restarts.

Disable with FINANCE_AUTO_INTAKE_ENABLED=false or `finance worker --no-auto-intake`.
`finance worker --once` never runs discovery. These controls affect new automatic
jobs; already-queued work is still processed. No web timer or unrelated recurring
financial action is introduced.

Use a unique FINANCE_WORKER_ID for each worker process. Leases are renewed every
30 seconds and provider outcomes are persisted. A stopped worker's lease expires;
another worker can resume durable work. Explicit retryable blocked results use
the database's capped retry policy. Authentication failure stops immediately and
requires owner correction, with no password/URI guessing or automatic fallback.

A timed-out payment submission is uncertain. Inspect its durable payment/provider
reference and verify it; never clear state to force another send. Testnet funds
only are supported by the shipped payment executor. Restoring a state backup does
not revoke or undo a transaction already submitted to a provider.

## Backup, export and removal

Structured records live in the event's Supabase Postgres project. Private source,
procedure, evaluation and report artifacts live in finance-artifacts Storage.
Keep both in the event's backup/restore plan; database backups alone do not contain
the Storage object bytes. Keep FINANCE_TOKEN_ENCRYPTION_KEY in the owner's separate
protected secret backup so restored mailbox tokens remain decryptable. Never put
that key into report exports or ordinary application records.

Use the dashboard's source-linked report export for financial review, and the
owner's Supabase backup/export tools for full archival/handover. Verify a restore
in a separate event-owned project before claiming disaster recovery tested. Pause
workers before changing a restored provider connection; investigate previously
submitted external payments before resuming execution.

To remove: stop worker/OAuth server, revoke the director's Gmail grant and wallet
OAuth grant, remove hosted dashboard/backend deployments and their environment,
then follow the event's retention policy for its Supabase project/Storage and
billing resources. Removing this checkout does not delete hosted records or
external-provider transactions.

## Updating

Back up first. Review release notes and new SQL migrations. Keep old applied
migration files unchanged; a changed checksum stops the migration runner. Run
`uv sync --frozen --extra dev` (plus `--extra payments` only if used), pinned Hermes
bootstrap, migrations by the same receipt-tracked method, then checks. Update the
web with `npm ci && npm run build`. Recheck actual provider callbacks and a scoped
case after a release. Do not promote a procedure merely because dependencies or
a judge score changed; use its actual paired evaluation and invariant gates.

# Guided demo source bundle and public inference bounds

The seed is input data, not a successful model run. `app/demo.py` stores two
clearly labeled synthetic evidence artifacts through the actual evidence/case
path: an organizer's paid purchase with a personal-card note, and a sponsor's
commitment with a message saying payment has not been sent. The artifacts contain
factual documents, not expected decisions, grading instructions or model output.
No existing frozen learning source, context, suite or answer key was changed.

The trusted dispatcher calls:

```python
result = await seed_demo_bundle(settings, tools, db, job)
```

The job must be a scoped `intake` with authenticated `requested_by` and payload
`{"source": "demo_bundle"}`. An optional `bundle_version` must equal the persisted
compatibility identifier `finny-guided-sources-v1`; arbitrary source text/expected outcomes, cash and policy
overrides are rejected. The tool-bound organization/run must exactly match the
job. Service-only `assert_finance_demo_owner` checks the actual active,
unexpired `is_demo=true` run, current owner and current director membership
before each source unit. A private event or another visitor's run is rejected.

The result includes:

- `status`, `bundle_version`, `bundle_sha256` and `synthetic: true`.
- `source_results`: actual `source_id`, versioned `source_ref`, `case_id`,
  `status`, stable `review_key`, `review_required` and synthetic label.
- `suggested_prompts`: questions for actual subsequent director-message jobs,
  including a budget/cash question with no supplied opening statement.
- `cash_established_by_seed: false` and `payments_enabled: false`.

The dispatcher must queue each result with `review_required=true` through the
existing real `queue_case_review`, preserving `review_key`, before completing the
intake job. The seed does not insert completed jobs, findings, obligations,
balances, approvals, payments, skills, evaluations, promotions or learning badges.
Actual worker outcomes, including clarification, rejection and failure, are shown
as recorded. The visitor submits a suggested question as a real director message;
the text is not a canned answer.

Identity is stable per run and bundle version. Retrying an untouched open case
recovers a possible crash before queue insertion. Existing modified/reviewed/
closed cases are returned as `preserved` with `review_required=false`; the seed
does not reset their title, data, version or human finding. Existing source bytes
and financial records are preserved. A later corpus change requires a new bundle
version rather than silently rewriting a visitor's work.

## Migration 013

`202610250013_demo_seed_and_limits.sql` adds two protected outer allowances in
addition to migration 009's per-run limits:

- 120 reserved model calls over a demo owner's lifetime across all owned runs,
  including cancelled/expired runs and resets.
- 600 reserved model calls per UTC day across all public demos in the service.

Normal actor/Jev and improvement reservations pass through this check before
inference. Reservations remain charged after rejection, provider timeout or reset.
Duplicate or denied inner claims do not double charge. Owner/global locks make
parallel reservations atomic. Private event usage is not charged to these public
allowances. Historical normal/improvement reservations are backfilled exactly;
if historical usage already exceeds a new limit it stays visible and further
claims are denied. The migration neither clamps prior usage nor grants a fresh
allowance. Quiesce public inference while applying the migration so the backfill
and new guarded entrypoint form a clear operational boundary.

Visitors and worker credentials cannot directly update allowance tables or call
the old unguarded kernel entrypoint. An authenticated owner may read only their
own lifetime allowance. There is no visitor RPC to raise either public limit.
These limits bound model calls, not an exact dollar amount; actual usage/cost
receipts retain their existing known/unknown distinctions.

Every public provider path must reserve its actual bounded work before calling
inference. The text seed itself performs no OCR or model work. Any separately
enabled upload/OCR path needs its own scope-bound reservation; the existence of
the SQL guard is not proof an unreserved adapter is protected. Unlimited fresh
anonymous identities also remain a public-deployment gate: configure signup
verification/hCaptcha and request rate limits before publication. The service
daily cap limits aggregate spend but is not an identity-abuse or availability
solution. No public deployment was performed in this implementation.

## Local proof and limits

With the authorized isolated local PostgreSQL DSN, the targeted demo/upgrade,
existing runtime guard and engine integration set passed 41 tests. The seed
tests use actual SQL/case/source operations with declared private-Storage
fixtures. They cover wrong scope/owner/non-demo/current authority, expired and
cancelled runs, stable retry/crash recovery, preservation of human changes and
existing ledger/cash, lifetime accounting through reset, concurrent global cap,
duplicate/failed claim accounting, direct-access denial, and actual pre-013 to
013 upgrade including historical improvement usage. Ruff passed.

No live provider, hosted database, mailbox, payment or public demo call was made
by this builder. Browser/queue/actual actor acceptance is separate and belongs to
the coordinator's integration receipts. No learned success is inferred from
seeding or these local tests.

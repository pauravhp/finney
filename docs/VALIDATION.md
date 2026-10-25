# Validation and current limits

Current hosted evidence: [guided director demo](demo/GUIDED_DEMO_ACCEPTANCE.md).
The prepared fictional event, actual invoice amendment, director budget rejection,
organizer reimbursement, typed follow-up and private report download passed hosted
acceptance on functional source `025f278`. Source/response formatting was checked
against actual stored data after fixture gaps were found and corrected. Current
learning remains unpromoted: the 5.5 phase stopped at `no_defect`, and fresh final
cases remain unused. [Current loop](SELF_IMPROVEMENT_CURRENT.md) distinguishes the
engineering repairs and runtime preflights from learned improvement.

Earlier OpenCode + Harness2 evidence: [complete bounded comparison](build/LEARNING_ACCEPTANCE.md).
Validation improved from 6/16 to 11/16 correct attempts; final transfer was
rejected and no learned skill was activated. These are synthetic test results.

The implementation uses isolated Hermes, real provider calls and hosted Supabase.
The financial inputs used for acceptance are explicitly synthetic. Model answers,
provider responses, payments and improvement scores are never seeded as successes.
Raw live receipts, account identifiers, authorization callbacks and private runtime
state are excluded from this repository.

## Verified

These results describe the frozen Hermes baseline at `13ed80d`; later OpenCode +
Harness2 integration and comparisons have separate ownership and evidence.

- 639 Python tests and 28 subtests passed, including isolated PostgreSQL integration
  for authorization, finance invariants, version checks, migrations and concurrency.
- 48 web unit tests, 15 desktop/mobile browser checks, production build and TypeScript
  passed. Ten optional Auth SDK fixture checks and one desktop-only exclusion were
  skipped in the normal browser run; fixture checks are not live provider proof.
- Actual password sign-in, approved budget allocation, PDF upload/private Storage,
  extraction, queued Hermes review, Jev triage, persisted finding and close report.
- Actual private Realtime broadcast matched its audit event; native original-document
  download matched the uploaded bytes.
- Real Claude vision OCR with a durable call reservation and unverified-source status.
- Actual authenticated guided-demo seeding and two real source reviews. Cash remained
  unknown; no payment, approval or successful learning result was seeded.
- The authenticated baseline was deployed to [finney-beta.vercel.app](https://finney-beta.vercel.app).
  Actual hosted browser password sign-in, director membership, scoped snapshot and
  Gmail connected status passed. Unauthenticated scope requests returned401. No
  financial mutation or worker runtime switch was performed for the deployment.
- Actual director conversation persisted and rendered the provider's answer and
  consulted-source provenance without changing financial findings or financial records.

## Fresh standalone checkout

The published repository was also installed and tested without inherited app
runtime state:634 Python tests and28 subtests passed, with five explicit optional
Hermes-runtime checks skipped. The production build, TypeScript,48 web unit tests
and15 browser checks passed (the same11 documented browser skips).

That check initially exposed12 test failures: subprocess fixtures assumed a
bootstrapped Hermes interpreter existed. Their fixture now creates a temporary
stdlib-only interpreter layout and executes the explicit test script. Production
runtime verification remains unchanged. The full clean-checkout suite then passed.

## Learning evidence

The control path includes trace diagnosis, bounded candidate generation, immutable
paired validation/regression/transfer inputs, independent SQL promotion checks,
active-version loading and rollback. Local lifecycle tests use explicit model fixtures.
Live checks have produced rejected diagnoses/candidates and no measured promotion.
One fresh frozen operating review failed validation because its blockers omitted
supporting references; it never reached the reviewer or evaluation stages. A failure
is not counted as an improvement. See the build summaries for these distinctions.

## Still unverified or outside coverage

- Live learned improvement, untouched-transfer success and promotion.
- Coinbase wallet consent, funding and actual testnet payout/x402 settlement.
- Anonymous guest Auth and public signup confirmation/callback. Guest entry remains
  disabled and needs provider/anti-abuse configuration before public use.
- Nonempty live Gmail intake. The isolated readonly profile/history/empty-label path
  ran live; attachment processing also has local transport and SQL tests.
- Bank/Plaid reconciliation, tax filing and outbound vendor/sponsor messaging.
- Wallet links conservatively become unavailable when an event revision changes;
  existing submitted/request-linked payments can still be reconciled without resending.

Run the commands in the README against your own isolated test database. Never point
the integration-test database variable at an operating financial database.

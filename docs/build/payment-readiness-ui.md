# Payment progress and director replies

October25,2026 UTC. Source-only migration014 preserves the thirteen previously
applied migrations. No authorization, provider request, transfer, activation or
hosted migration was performed by this builder.

Approvals now include the initial approved testnet execution control and the
existing-payment reconciliation control. Pending Wallet requests expose an HTTPS
approval link, exact proposal/payment/job references and explicit pending copy.
Checking again queues execute_payment for the same proposal; the executor retains
its existing uncertain-request resume and no-resend behavior. Confirmed copy
requires an actual confirmed payment record, never merely a completed job.

Migration014 projects only whitelisted payment job status/reason and canonical
payment linkage. Approval URLs require a matching provider request, exact current
proposal and current human authority. The link survives later poll jobs/history
limits, then disappears after confirmation or authority expiry/change. Only
current eligible authenticated humans receive these fields; solo mode exposes
them only to the director. Actor/service snapshots and public demos receive empty
payment projections. Direct browser jobs.result/payments.receipt reads are denied
so the projection cannot be bypassed through raw REST reads.

Expanded cases also render data.director_responses as Finney’s replies. Actual text
is React-escaped with preserved line breaks, followed by recorded consulted source
IDs and provenance. Existing source evidence/finding data and its inspector remain
unchanged. The reply renderer confers no financial approval or settlement state.

Verification:19new actual isolated SQL tests;117combined SQL budget/approval tests
passed. All34web unit tests passed, as did production build/TypeScript and two
desktop/mobile browser component checks. The browser fixture captured the exact
same-proposal reconciliation command, escaped reply markup, pre-wrap behavior and
absence of horizontal overflow. All provider values/messages were explicitly
labeled fixtures; no real Wallet URL was opened.

Impeccable's narrow hardening workflow preserved the incumbent design. Desktop
and mobile screenshots were inspected in two bounded rounds. The first mobile
capture showed the inherited reversed action order; the scoped payment row now
keeps Wallet approval before checking the payment. The final captures include the
reply renderer. The detector reported incumbent CSS/design-token advisories;
the new reply component scan was clean. No unrelated design drift was repaired.

The first SQL projection test caught PostgreSQL's bounded-regex repetition limit;
the request-ID length check now uses a separate length predicate. Fixture request
IDs were also made unique across test scopes, preserving the global duplicate
provider-reference constraint.

Local commands:

- `FINANCE_TEST_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres uv run --extra dev --extra payments pytest -q tests/test_payment_visibility.py tests/test_finance_postgres.py tests/test_finance_approval_policy.py tests/test_finance_budget.py`
- In web/: `npm test`, `npm run build`,
  `npx playwright test tests/payment-execution.browser.spec.ts`.

Fixture screenshots are private ignored outputs under
`.state/ui-review/payment-execution-desktop.png` and
`.state/ui-review/payment-execution-mobile.png`.

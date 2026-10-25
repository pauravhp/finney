# Payment reconciliation after budget changes

October 25, 2026. Migration016 changes only the internal budget wrapper retained
behind migration013's public kernel. This builder did not apply hosted migrations
or make provider, Wallet, authorization or payment calls.

An existing scoped payment in submitting, uncertain, submitted or confirmed state
can replay its reservation so the executor can inspect the durable state, poll an
existing Wallet request and verify its receipt. A later unassigned payable or
overcommitted budget no longer blocks that reconciliation. The executor never
resends these states; a submitting payment without a usable request reference
remains blocked for investigation.

New or reserved payments still require current budget capacity, and the first
submission claim still requires both budget capacity and current exact human
approval authority. Existing source, scope, demo, idempotency, receipt and ledger
guards are unchanged. Internal kernel entrypoints remain unavailable to service
clients; the public demo owner/global inference limits remain outside the wrapper.

Wallet approval links retain their conservative current global-revision check.
Recording an unrelated director question can therefore hide an outstanding link.
Migration016 does not restore stale links or grant new external approval
authority. This is a known UX limitation requiring a separate, precise authority
invalidation design. It does not block checking an already-created request or
verifying an existing transaction receipt.

Verification used actual isolated PostgreSQL at localhost:55439 and the actual
PaymentExecutor with explicitly labeled fixture Wallet/chain responses. All 14
new tests passed: four existing states across two later budget defects, new and
reserved send denial, exact receipt rejection and internal-entrypoint denial.
The combined payment, visibility, kernel, approval and budget suites passed 151
tests; four additional actual SQL demo-budget tests passed. Ruff passed. Fixture
reconciliation asserted zero sends and exactly one ledger posting on repeated
confirmation. These results do not establish live provider settlement.

Commands from the application root:

- `FINANCE_TEST_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres uv run --extra dev --extra payments pytest -q tests/test_payment_reconciliation_budget.py tests/test_payment_visibility.py tests/test_finance_postgres.py tests/test_finance_approval_policy.py tests/test_finance_budget.py tests/test_payments.py`
- `FINANCE_TEST_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres uv run --extra dev --extra payments pytest -q tests/test_demo.py -k 'budget or reservation or previous_kernel' tests/test_demo_upgrade.py`
- `uv run ruff check tests/test_payment_reconciliation_budget.py`

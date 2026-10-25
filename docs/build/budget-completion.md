# Budget and director-work completion receipt

October24,2026 Pacific / October25 05:23UTC. Source-only migration010;
no hosted migration, provider call, deployment, payment or live inference.

Budget changes are proposals until an authenticated current director approves
them. They bind the exact canonical request, current line version and financial
run revision. Rejection has no allocation effect; stale proposals cannot apply.
An approval cannot reduce an allocation below existing commitments, and no
allocation change can proceed while a payment is unsettled. The configured
one/two-person policy still governs payments separately.

Budget totals include settled spend and outstanding commitments, excluding
cancelled obligations. Once an event has any approved budget lines, payment
preparation/reservation/submission is blocked if a positive payable is unassigned
or line commitments exceed the approved allocation. Existing events with no
budget lines preserve their previous payment behavior. Obligation budget links
must belong to this event/run/currency; updates now actually apply the link in
the same locked version. This is allocation accounting, not fund segregation.

Director messages accept only message and optional scoped case_id. The original
envelope is retained in jobs.request_payload, so trusted worker case/source
enrichment cannot break an idempotent browser retry. Prepared review persistence
accepts the director_message command while retaining exact trace/job/case/output
guards. get_budget_plan evaluation reads use only a frozen captured budget.

Original uploads are permitted only under the current member's active scoped
uploads prefix. The test platform now includes Supabase's foldername behavior
(path directories excluding the final filename). Local SQL caught a real policy
bug: an unqualified name inside a correlated subquery resolved demo_runs.name.
The policy now explicitly references storage.objects.name; valid insertion
passes while other runs, artifact paths, traversal, viewers and inactive runs
remain denied. The draft's unparenthesized SQL CASE was also corrected before
claiming a migration pass. One test fixture lacked opening cash and was fixed
without weakening the cash gate.

Verification:134focused tests passed on isolated local PostgreSQL; Ruff passed
for changed Python files. The new budget file contributes37tests, including
concurrent approval/CAS, exact request replays, malformed/null inputs, scope and
currency links, overcommit/payment checks, original message envelope recovery,
actual trace-backed director message annotation and Storage INSERT/RLS.

Command, run from the app root:
`FINANCE_TEST_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres uv run --extra dev --extra payments pytest -q tests/test_finance_budget.py tests/test_finance_runtime_guards.py tests/test_finance_postgres.py tests/test_finance_approval_policy.py tests/test_finance_domain.py`.

All SQL databases are random temporary test databases created/dropped on that
loopback server. Fixtures are explicitly labeled; none represent live humans,
financial documents or provider settlement. The packaging migration renderer
loads sorted *.sql files, so009/010 are included without a hardcoded list.

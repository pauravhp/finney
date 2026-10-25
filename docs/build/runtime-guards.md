# Runtime/evidence completion receipt

October 25, 2026. Migration009 is source-only until the coordinator applies it.
No hosted migration, provider call, payment, deployment or improvement inference
was performed for this change. All financial/provider inputs below are fixtures.

The database now rejects every payment preparation/reservation/submission/
confirmation operation for a public demo run, including a privileged worker call.
It also refuses real income posting for that run. Old kernel/income entrypoints
are revoked from workers, so callers cannot skip the wrapper. Provider access
additionally requires `assert_payment_run_authorized(tools, settings)` before any
wallet/facilitator call: credentials bind to the explicit worker
FINANCE_ORGANIZATION_ID/FINANCE_RUN_ID and validated sender, and the database
rechecks that the run is private and active. This does not change the director's
chosen one/two-person human approval policy.

Obligations require actual current scoped source IDs/versions. Actor text may
request only expected/reported evidence. An authenticated current director can
explicitly attest an obligation through `attest_finance_obligation`, with version
CAS, source validation and an audit receipt. Material changes downgrade the old
attestation; actual confirmed payment receipts establish provider confirmation.
No statement-confirmation workflow or fake evidence was introduced.

Durable model reservations default to120calls per public run and1000calls per
private event run, with3improvement attempts. These are lifetime reservations,
not daily limits: a failed/abandoned call remains charged. Only an authenticated
director of a private event can raise limits through
`set_finance_execution_limits`; it cannot erase prior consumption. Public demo
owners and service/model tools cannot raise them. Fresh demo runs have their own
budgets; deployment-wide rate limits remain a separate requirement.

Trusted tools and fields:

- `reserve_run_inference`: reservation_id(UUID),max_model_calls(1..40).
- `claim_improvement_attempt`: attempt_id,trace_id,baseline_version_id(UUIDs),
  suite_id,suite_manifest_sha256,evaluator_version,max_model_calls,
  case_manifest[{case_key,group,source_snapshot_hash}].
- `claim_improvement_holdout`: attempt_id,suite_id,transfer_fingerprints[SHA256].
  Every frozen transfer fingerprint is atomically consumed at first use, across
  all attempts/baselines in this run. A validation rejection consumes none.
- `finish_improvement_attempt`: attempt_id,status(blocked/rejected/promoted),
  model_calls_used,reason,optional eval_run_id. No refund or permission renewal.

Claims return claimed(boolean),identity and a reason on denial. Reusing a job or
trace claim returns denial rather than renewed inference authority. The SQL
promotion gate independently checks the frozen complete case manifest, exact
baseline/candidate pairs, all validation/regression/transfer groups, matching
versions/hashes, consumed holdouts, no hard/regression/transfer failure, no loss
on previously correct cases, and a measured correctness or correct-pair tool
count gain. A caller-supplied gate_passed flag alone cannot promote anything.

Verification used only isolated temporary databases at
`postgresql://postgres:postgres@127.0.0.1:5432/postgres` with explicit test-only Supabase
platform stubs. The focused suite covers actual SQL grants, scope/version checks,
approval compatibility, competing reservations/attempts/holdouts and promotion
positive/negative paths. Python provider authorization checks reject before any
network operation when configuration, scope or evaluation mode is invalid.

Result:97focused tests passed; Ruff passed for the changed Python files. Command:
`FINANCE_TEST_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres uv run --extra dev --extra payments pytest -q tests/test_finance_runtime_guards.py tests/test_finance_postgres.py tests/test_finance_approval_policy.py tests/test_finance_domain.py`.

Two verification corrections were retained: the first migration run found that
trace_events needed a composite uniqueness constraint for a scoped foreign key;
that constraint was added. Two initial assertions tried to read protected budget
tables as service_role; they now use the test administrator for readback instead
of granting the worker unnecessary table privileges.

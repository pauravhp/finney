# Online Harness2 candidate search

The normal queued `evaluate_improvement` job can select actual pinned Harness2
candidate search. It keeps the existing source-supported diagnosis gate, frozen
paired validation/regression, consumed transfer holdout, independent financial
checks and SQL activation/CAS. Search selection alone never activates a skill.

Default behavior remains `single_patch` until the online path passes live
acceptance. To enable after installing the pinned OpenCode runtime, pinned
Harness2 dependency and migration **019**:

```dotenv
FINANCE_ACTOR_RUNTIME=opencode
FINANCE_IMPROVEMENT_METHOD=harness2
# Optional app-owned copy of the exact pinned binary:
FINANCE_OPENCODE_BINARY=
```

Settings, the job dispatcher, engine and candidate factory all reject a Harness2
search with a Hermes actor. This does not replace the isolated Hermes mailbox
connector. No public endpoint or browser command can supply a callback, budget,
protected answer, policy override or mutable harness component.

## Data and authority boundary

`app/improvement/harness2_candidate.py` receives only the source trace, baseline
skill, trusted tool port, fixed runtime context, immutable policy and bounded call
reservation function. It receives no protected suite, evaluator, expected answer,
validation/regression/transfer snapshot or holdout file.

Training is reconstructed only from successful captured `get_case`,
`read_document`, `get_obligations`, `get_financial_position` and `get_budget_plan`
observations. Failed actors' tool observations come from their checksum-verified
private diagnostic artifact. Raw failed final output is excluded from the search
packet. Missing cash/budget/obligation observations stay unavailable; there is no
live database/source fallback to silently change the historical inputs.

A single observed case plus versioned document content is required. A failed
trace's initial case ID/version must match the captured case. Truncated private
diagnostics, conflicting source content and missing source observations block the
search without inferring a replacement snapshot. The snapshot, fixed context,
policy, baseline hash and source provenance are frozen to private Storage before
the first probe/editor call.

Actual `run_harness_search` executes the pinned upstream
Propose–Probe–Compose–Reflect schedule with `mode=parallel`, `k=1`. Probes use the
real OpenCode actor and `tools.for_evaluation(frozen_snapshot)`, with read tools
only and effects disabled. Only the investigation procedure can change; both
the adapter and engine validate exact protected-prefix/suffix preservation.

Editor responses use the native OpenCode StructuredOutput-only mode, with one
reserved provider call and no shell, file-reader or finance tools. Their Harness2 context contains the captured input
packet and actual probe observations, with no financial answer key. The temporary
library, proposals, probes, missions and selection files are persisted as indexed,
SHA-bound JSON parts plus a private manifest. Each part is bounded by its actual
serialized UTF-8 size to 8 MB, below the artifact tool's 10 MiB limit; escaped
Unicode and quotes cannot silently push a raw-byte estimate over that limit.
A scoped `harness2_candidate_search` trace links the frozen inputs and
search receipts. Probe failures retain their original private diagnostics and
safe failure observations; they are not treated as correct finance decisions.
No-op selection is explicitly rejected; it does not fall back to another editor.

The candidate then follows the original paired engine and independent gates.
Automatic Harness2 jobs select the fixed four-case [corpus subset](../CORPUS_ONLINE_SUBSET.md),
including its shared final-partition consumption marker.
Existing unseen-transfer consumption and SQL promotion conditions are unchanged.

## Budget

Single-patch attempts still reserve at most **40** calls. Explicit Harness2
attempts may reserve at most **96**. The k=1 online schedule limits each of its
four probes to six model calls and reserves every probe/editor allowance before
provider invocation. Its conservative search bound is 28 calls; triage/diagnosis
add two, leaving 66 under the 96-call reservation. The current four-case protected
suite can execute eight paired actors at up to eight calls each within that bound.
Larger or unusually expensive suites fail at the existing shared call budget.

Migration 019 records `improvement_method` on the attempt, widens only explicit
Harness2 attempt reservations to 96, and leaves ordinary `reserve_run_inference`
and single-patch claims capped at 40. It updates both the inner attempt guard and
outer demo owner/day guard, failing closed if those known function definitions
have drifted. Per-run totals, attempt counts, persistent demo-owner lifetime
limits and service UTC-day limits still apply. Failed/duplicate attempts cannot
charge a second owner/day allowance; reservations are not refunded after failure
or reset. A public owner with insufficient remaining allowance is blocked before
triage or search inference begins.

## Verification and limits

These staging checks use scripted actor/editor outputs and actual pinned
Harness2 recursion. The PostgreSQL checks create/drop their own isolated random
database on the explicitly supplied local test server; they do not mutate the
hosted application or the live comparison checkout.

```bash
python -m pytest tests/test_harness2_candidate.py tests/test_harness2_budget_postgres.py tests/test_harness2_search.py tests/test_improvement_lifecycle.py tests/test_improvement_postgres.py tests/test_finance_runtime_guards.py tests/test_demo.py -q
ruff check app/improvement/harness2_candidate.py app/improvement/engine.py app/runtime/jobs.py app/config.py tests/test_harness2_candidate.py tests/test_harness2_budget_postgres.py
```

Verified: actual upstream schedule runs four probes/four editor calls; training
is persisted before execution; original failed diagnostics are hash-bound;
protected suite data is excluded from callback arguments; no-op/low-budget
searches do not fall back; queue dispatch chooses the callback and 96 allowance;
existing paired evaluation and CAS execute afterward. Actual PostgreSQL tests
cover 96 acceptance, 97 rejection, unchanged legacy/ordinary 40 caps, unchanged
per-run/owner/day limits and duplicate charging. Existing lifecycle/PG promotion
and rollback tests also pass with the migration applied.

The first migration test found a PL/pgSQL `CASE` expression needed parentheses in
an `IF` condition; corrected before the successful isolated migration/application
tests. An initial queue fixture omitted required scope IDs; the application
correctly blocked it, and the fixture was repaired. These were staging failures,
not live model outcomes.

Final staged result: **124 passed, 2 skipped, 28 subtests passed** in 2.60 seconds;
Ruff passed for all changed Python modules and new tests. Skips require the
explicitly installed Hermes source and do not imply provider execution.

No live model call, online learned gain, deployment, payment or canonical source
change was performed by this work. The default stays single-patch until the
coordinator records real online acceptance.

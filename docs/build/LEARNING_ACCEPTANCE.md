# First complete OpenCode + Harness2 comparison

The real provider-backed experiment produced an observed validation gain, then
**rejected the candidate at the final transfer gate**. No learned skill was
activated and no payments, approvals or settlements were executed by the benchmark.

The corpus has 24 source-informed synthetic cases and 72 source records, with
independent AI review rather than professional finance validation. The bounded
experiment used two development cases for search, eight validation cases and six
heldout cases. Validation and heldout each used two attempts per version, with
baseline/candidate order reversed on the second pass. All 60 scored attempts,
including failures, remain in the private hosted record.

| Phase | Baseline | Harness2 candidate | Outcome |
| --- | --- | --- | --- |
| Validation: 8 cases × 2 attempts | 6/16 correct | 11/16 correct | Passed: no paired regressions or hard-invariant failures |
| Heldout: 6 cases × 2 attempts | 3/12 correct | 8/12 correct | Rejected: candidate did not pass every final attempt |

There were three heldout startup timeouts before any provider request: two
baseline attempts and one candidate attempt. They occurred during concurrent
release checks on the shared host; load reached 43 on eight logical CPUs. The
checks were stopped and subsequent invocations resumed normal execution. Resource
contention is consistent with this timing, but no controlled causal test was run.
The failed attempts were retained, with no heldout retries or scoring changes.
This incident prevents treating the heldout run as a clean measure of financial
reasoning alone.

The candidate also had three completed-but-incorrect heldout outputs. Those
errors concerned missing necessary stage blockers or unsupported stage
requirements. Thus the timeout was not the only reason to withhold promotion.
The final dataset partition remains consumed for this organization/run/manifest;
a new run is not evidence that these same cases are globally unseen.

The candidate expanded the original four-step procedure with explicit payer and
recipient classification, existing-obligation checks, cash/budget reads and
operation-stage evidence requirements. The protected authority boundary remained
unchanged. Among validation pairs where both versions were correct, the candidate
used 48 finance-tool calls versus 45 for baseline; no efficiency gain is claimed.

The small runtime comparison on two development cases found Hermes correct on
1/2 and OpenCode correct on 2/2. This is a compatibility smoke comparison, not
sufficient evidence that OpenCode generally outperforms Hermes.

## Execution identity and provenance

All nine frozen executor/search/evaluator source hashes match commit `189a350`.
The actual pinned upstream Harness2 Propose–Probe–Compose–Reflect implementation
ran through eight native OpenCode editor invocations and eight OpenCode probes.
Actor model: `claude-sonnet-4-6`, 2,400 output-token cap and six-call allowance;
editor output cap: 3,500, with one forwarded request per stage. The conservative
reserved bound was 416 of the configured 480-call ceiling, not a dollar-cost claim.
Expected answers and protected cases were excluded from the editor/search inputs.

Earlier integration failures remain recorded separately: a pre-inference path
constructor issue, reference/action schema issues, a direct editor returning prose,
and the pinned runtime's one-step assistant-prefill incompatibility. Their fixes
were engineering work, not learned improvements. The successful run used the
fixed native structured editor before any search or validation invocation.

A fresh event exposed a missing baseline-version reference in the benchmark's
original storage path. Future comparisons now preserve the exact bundled baseline
as a non-active reference. Any historical linkage repair is performed only after
terminal completion against frozen hashes, audited separately, and preserves all
scores, outputs, metrics, statuses and active skills. It is not another experiment.

A later ordinary queued review exposed an output-contract mismatch: the runtime
accepted a prose classification that the operating review persister already
required to be an identifier. The producer schema, guidance and shared validator
were aligned afterward. The historical experiment was not regraded, and its
scores describe the original frozen checks, not full operating acceptance under
the corrected contract. See [classification alignment](CLASSIFICATION_CONTRACT_ALIGNMENT.md)
and [rejected-review intake](QUEUED_REVIEW_INTAKE.md).

## Demo interpretation

The Learning view shows an actual recorded execution: candidate procedure,
verified stored diff, paired results and rejection. It must not be presented as
fresh inference or a promoted production skill. The normal source-to-review flow
is verified separately through the real durable worker. Builds and scripted
browser/runtime checks must run after a paid experiment on this shared host.

## Release checks

The assembled integration passed 740 Python tests and 78 subtests (29 explicit
skips), Ruff, 53 web unit tests, TypeScript, the production build, and 29 browser
tests (11 explicit skips). The final backend and browser runs were sequential;
browser concurrency was limited to one worker. Wheel checks included all 20
migrations and the 26 corpus/manifest files. Scripted runtime/browser fixtures
are not counted as live financial learning evidence.

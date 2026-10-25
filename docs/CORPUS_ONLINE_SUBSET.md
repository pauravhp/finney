# Four-case online corpus evaluation

The online adapter selects the following frozen cases before new inference:
`fc-016` and `fc-014` for validation, `fc-015` for regression, `fc-019` for transfer.
They cover organizer reimbursement after a refund, conflicting payer evidence,
restricted cash versus budget/reporting, and distinct personal payer shares.
These are four source-informed synthetic cases, not the full 24-case corpus,
field validation or measured evidence of a gain. No paid model calls were made in
building/testing this adapter. Do not claim repeated-run variability: the online
engine performs one paired baseline/candidate replay per selected case.

The full 24-case, two-repetition comparison remains the offline benchmark. The
online subset uses the existing 96-call Harness2 allowance and unchanged engine
and promotion controls. At normal 8-iteration actor limits, its maximum is the
review/triage overhead, bounded search and eight evaluation executions; it fits
the bound. The engine still stops when its actual remaining allowance is exhausted.
No extra inference is added to repair malformed model output.

`corpus_online.py` builds an ordinary `ProtectedSuite` from the frozen
`FinanceDataset` and delegates verification to its real scorer and prepare-only
finance kernel. The suite exposes minimal expected action fields only to trusted
evaluator code; corpus identity, source/version, stage and report checks remain
in the protected scorer. Actors receive source snapshots and ordinary captured
finance tools. Neither the diagnosis nor Harness2 search receives suite cases or
expected answers; its training case remains the observed source trace.

Automatic review jobs use the corpus suite only when
`finance_improvement_method=harness2`. Legacy automatic jobs retain suite v5 by
default. The queue helper accepts an optional trusted suite ID. Runtime execution
rejects the corpus suite under a different method rather than silently changing
its evaluation. Existing queued v5 jobs are not rewritten or resubmitted.

A `CorpusEvaluationTools` facade wraps only the trusted improvement coordinator.
It delegates `scope`, `for_evaluation` and `call`, and exposes no dynamic database
or connector attributes. Evaluated actors receive the underlying prepare-only
snapshot client, never this facade. On a successful `save_skill_version` it
remembers the persisted candidate artifact hash. When the unchanged engine first
requests `claim_improvement_holdout`, after validation/regression gate success,
the facade first calls migration018's `claim_finance_learning_holdout` with the
same corpus manifest hash used by the offline benchmark. Only a successful global
claim permits the original native holdout claim. Both native holdout and final
promotion/CAS controls remain authoritative.

The global claim consumes the **whole corpus final partition** in that existing
organization/run, despite online inference using only fc-019. A later offline
benchmark in that scope cannot call the same final partition untouched, and vice
versa. A fresh wrapper, changed candidate, retried job or different subset does
not bypass this shared marker. Missing candidate hashes, mismatched suite IDs,
invalid attempt identities, denied global claims or native holdout denials fail
closed before transfer actor execution. Global consumption remains recorded if a
subsequent native claim or provider call fails; this is intentional. Do not retry
final inference to seek a better score. A new independently authored untouched
corpus is required for new final-test evidence.

The implementation contains focused changes to suites, runtime job dispatch, the queue
helper and service dispatch, plus the new adapter/tests/document. No engine,
financial permissions, expected labels, corpus packets or manifest were edited.
`tests/test_corpus_online.py` uses declared scripted fixtures, the real
FinanceDataset/scorer/kernel and unchanged ImprovementEngine. Its promotion result
is a control-flow fixture, not a learned or live financial outcome.

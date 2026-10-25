# Continuing an interrupted archived search

This recovery is restricted to the boundary after an already completed and
archived Harness2 search, before any candidate or paired evaluation was saved.
It does not start a new search, retry a scored case, claim another attempt,
reset reservations or modify a candidate. The original failed job remains failed.

Trusted coordinator entrypoint:

```python
from app.improvement.continuation import continue_archived_search

result = await continue_archived_search(
    connection=read_only_psycopg_connection,
    tools=scoped_integrated_tools,
    actor=original_model_opencode_actor,
    attempt_id=original_attempt_id,
    archive_receipt=verified_archive_manifest_receipt,
)
```

Pass `validate_only=True` first for a read-only proof check with no continuation
claim and no model calls. Actual execution repeats every check before claiming.

The caller must supply the existing private scope and original model settings.
The function independently reads the original database attempt, failed job,
phase receipts and immutable artifacts. It checks the active baseline, qualified
diagnosis pointers, original runtime context, full frozen evaluation manifest,
model settings, pinned runtimes, captured training snapshot, archived selected
candidate and permitted edit boundary. The archive must have been stored during
the original failed job. Existing candidate/evaluation/holdout/continuation work
causes refusal. Caller-supplied candidate text or expected outcomes are not inputs.

A one-shot durable trace uses a deterministic attempt key and a fresh execution
nonce. Two concurrent invocations cannot both proceed: the existing kernel's
idempotency conflict rejects the second before inference. An ambiguous write is
not automatically retried. The same attempt's original 96-call reservation stays
charged. This narrowly supported schedule starts with 30 conservatively charged
calls (two diagnosis/triage plus the already archived 28-call search bound), and
the eight paired actor runs fit in at most 64 additional calls. Model identity,
output limits and context must match the original manifest; a model upgrade
requires a different future experiment.

Normal execution and continuation call the same extracted post-search method.
It saves the exact candidate, performs validation and regression, claims the
shared and native final holdouts only after the existing gate passes, and uses
the existing final gate and atomic activation. A failed candidate stays rejected.
The continuation has no direct activation shortcut. Every final outcome preserves
the original failed job and adds separate recovery/evaluation evidence.

Verification uses actual isolated PostgreSQL with scripted actors and fixture
Storage: successful native promotion/unchanged reservation accounting, failed
transfer/no activation, concurrent one-shot admission, and zero calls after a
model mismatch, changed archive hash, prior continuation, terminal attempt or
nonfailed job. These are engineering fixtures, not live learning evidence.

That PostgreSQL rejection test also exposed an older receipt collision: a rejected
promotion and its final audit trace used the same global idempotency key. Only
the final trace now receives a `:result-trace` suffix. No quality gate or rejected
outcome changed; this lets a genuine rejection finish and remain inspectable.

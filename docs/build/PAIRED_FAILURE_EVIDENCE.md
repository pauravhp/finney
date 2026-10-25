# Private evidence for failed paired evaluations

The continued October 25 phase completed only its first validation baseline
attempt: five provider calls, eight tool calls, hard invariants passed and overall
correctness failed. The next invocation was that case's candidate. It aborted
with `opencode_provider_or_runtime_failure`, leaving a conservative 43 of 96 calls
charged. No regression or final transfer was evaluated and no skill was promoted.

The prior engine aborted safely but did not preserve that paired actor exception's
private diagnostic. The exact cause of this candidate failure is therefore not
established. Earlier search-probe truncation evidence cannot be substituted for
this missing diagnostic. The original blocked outcome is unchanged.

For future attempts, the same abort path now stores the existing bounded private
failure artifact and returns only its locator/hash with case, variant, group,
source-snapshot hash and safe error code. Incomplete evaluation metrics and the
blocked trace carry that reference. Raw source/provider output remains private.
If diagnostic persistence fails, the original actor error remains primary and
the diagnostic is explicitly unavailable; no exception body is published.

This does not retry an actor, create a successful score for an incomplete output,
refund its reserved allowance, open a holdout or change a promotion gate.
Tests cover private-data separation, bounded truncation, failed diagnostic upload,
absent diagnostics, and actual PostgreSQL terminalization with no activation.

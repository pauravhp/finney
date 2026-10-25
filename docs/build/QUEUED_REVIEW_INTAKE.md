# Learning from a rejected operating review

A real queued synthetic expense review completed through OpenCode and Jev,
identified the organizer and amount, and persisted a reported obligation and a
finding. Its final annotation was rejected because the `decision` field contained
prose instead of the existing identifier format. The completed-to-blocked
transition skipped the automatic-learning branch. The original blocked result
and all actual tool-produced records remain intact.

The service now considers automatic diagnosis after checking persistence. Only
an eligible completed review with the exact trusted rejection
`unsupported_prepared_review_output` takes the new route. Scope, provenance,
source-version and concurrency rejections remain excluded. The source-trace
idempotency key prevents duplicate children. Fixed feedback states that this may
be an interface issue and does not establish a skill defect; the reviewer must
still find source-supported evidence. It does not replay the operating task or
infer approval, payment, settlement or absence of earlier effects.

Migration 021 adds `opencode_timeout` to the same private SQL reason guard already
used for reserved failed traces, matching the Python allowlist. It leaves source,
reservation, output-exclusion, run/owner/day budget, holdout and promotion checks
unchanged. Zero provider calls are admissible as diagnostic evidence; they are
not a financial finding or evidence of an editable procedure defect.

Focused service tests use the real review persister and verify one child after
prose rejection, unchanged blocked outcomes and earlier reported records, and no
enqueue for provenance/race failures. Disposable PostgreSQL checks verify timeout
admission, forged-record rejection, unchanged ordinary 40-call limits and dedupe.
No protected corpus answers, source documents or historical scores were changed.

A missed historical child may be recovered through the same trusted queue helper
only after checking its unchanged stored job, completed trace, active baseline and
captured source versions. Such recovery is separately audited. It must not edit
the original outcome, force a diagnosis/candidate, or bypass any inference gate.

The assembled follow-up passed **797 Python tests and 80 subtests**, with 29
explicit skips, plus Ruff and diff checks. This includes the actual pinned runtime
with scripted providers and disposable PostgreSQL guard checks. Web code is
unchanged from the previously verified release.

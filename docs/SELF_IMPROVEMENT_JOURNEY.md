# How Finney's self-improvement loop evolved

This is the engineering and experimental history, including failed attempts.
For the current mechanism, see [the current loop](SELF_IMPROVEMENT_CURRENT.md).
Synthetic examples, scripted tests, real model executions and production effects
are different evidence levels throughout this record.

## 1. Finance work and bounded learning

The original Hermes-based build separated the operating finance agent from the
improver. The agent investigates sources and proposes work; deterministic finance
code controls amounts, approvals, versions and settlement. Jev reviews traces,
and a reasoning reviewer decides whether the evidence supports a procedure defect.
Only the investigation section of the organizer-expenses skill may change.

The first live reviews exposed strict output failures, including blockers without
supporting references. Failed outputs originally stopped before diagnosis. More
mocked successes would not address that coverage gap: the failure itself needed
to become inspectable evidence without being accepted as a financial decision.

## 2. OpenCode, Harness2 and richer evidence

We adopted an app-owned pinned OpenCode actor and actual pinned Google Research
Harness2 search, retaining the finance kernel, hosted records and approval gates.
Isolated Hermes helpers remain for Gmail. Personal Hermes is not a dependency.
The 24-case source-informed synthetic corpus contains 72 sources, split into ten
development, eight validation and six heldout cases. Independent AI review is
documented; finance-professional/customer validation is not claimed.

The evaluator checks remaining liability, recipient, source versions, stage-specific
requirements and reporting, alongside hard financial invariants. Failed trace
intake requires positive eligibility and checksum-bound private diagnostics.
Decision-time tool observations are replayed without silently filling gaps from
later records. Actor/editor tools cannot read the scoring answers.

## 3. Integration failures before a measurable comparison

- A path-construction failure blocked bootstrap before inference.
- The first provider-backed search produced no changed candidate: actor reference
  shapes failed and the direct editor returned prose instead of the required object.
- Explicit nested reference schemas and a native structured OpenCode editor fixed
  those contracts. These were engineering repairs, not learned improvements.
- A second search failed because the runtime's one-step hint produced an assistant
  prefill rejected by the provider. The runtime hint was corrected while the external
  one-call editor allowance remained enforced.

Failures and diagnostics were retained. No historical score was rewritten to turn
these repairs into learning gains.

## 4. First complete real comparison

Experiment `82fcd804-1ddf-498d-91c6-823cebfeb50d` ran eight native editor stages and
eight probes through upstream Harness2. Across 60 scored attempts, validation
improved from **6/16 to 11/16**, without paired regressions. Heldout results improved
from **3/12 to 8/12**, but the candidate failed the final all-correct transfer gate.
**No skill was activated.**

The candidate had three completed stage/blocker errors and one startup timeout.
Two baseline attempts also timed out. Concurrent release checks overloaded the
shared host; resource contention fits the timing but was not causally isolated.
All failures counted. The old final partition is consumed, including when a new
experiment ID is used. Correct-pair tool calls increased from 45 to 48; no efficiency
gain is claimed. See [the frozen acceptance](build/LEARNING_ACCEPTANCE.md).

## 5. Real operating intake exposed a different contract gap

A real authenticated upload of a labeled synthetic receipt led to five OpenCode
calls and a Jev review. The actor recorded a USD 153.27 organizer liability, then
its final review annotation failed because a classification was prose instead of
the persistence contract's identifier. Earlier legitimate tool effects remained.
Failed final output does not mean that nothing happened.

We aligned the producer/validator contract and repaired missed post-persistence
diagnosis scheduling. The recovered diagnosis used two calls and returned
`policy_question`; it did not support a mutable procedure defect and generated no
patch. A later director question completed through real tools and persisted an
evidence-backed reply. These engineering fixes did not regrade the old benchmark.
See [live acceptance](build/LIVE_DEMO_ACCEPTANCE.md).

## 6. Next acceptance cycle — in progress

The owner authorized a complete finance exception with amended evidence and a
denied approval, policy/stage fixes, independently authored fresh holdouts, and a
quiet-host learning run. Current audit found that diagnosis could receive the
evaluation suite's policy even when the operating actor had not explicitly seen
it. The fix must bind diagnosis/search to the captured operating policy and keep
evaluation policy separate. Older traces cannot acquire policy provenance later.

Stage labels also need clear distinctions: recording an evidence-backed reported
liability is different from preparing exact payment terms, executing with human
authorization, or asserting independently verified settlement. Ambiguous labels
in consumed cases are debugging evidence, not new holdouts.

New UI transfer, autonomous inbox/wake work and judge-prompt support proceed in
parallel. Heavy builds/tests must finish before the paid comparison. The next
candidate, evaluator, cases and gates will be frozen before inference. No patch,
score adjustment, repeat-until-pass run or manual activation is justified by a
demo deadline. Results will be appended here whether the attempt promotes,
rejects, or stops before candidate creation.

## 7. Amended evidence revealed a learning-evidence failure

The next quiet-host operating review correctly recorded the synthetic Harbor AV
invoice at USD 480.00. Diagnosis returned `no_defect`; it generated no patch and
opened no holdouts. The amended invoice correctly changed the model's conclusion
to USD 420.00, but its mutation cited both the original and superseding source.
The database refused that update, so the actual recorded liability stayed at
USD 480.00. The actor disclosed this failure rather than claiming a successful write.

The tool exposed only a generic `SupabaseError`. Diagnosis consequently called it
an infrastructure problem and again produced no patch. This was a substantive
evidence-quality gap: the rejection of stale operative evidence had become
indistinguishable from an unavailable provider. The prior trace and its incorrect
diagnostic interpretation remain intact.

The repair exposes only exact allowlisted domain-rejection tokens and fixed
recovery guidance, never raw database response bodies. Both runtimes receive the
same feedback. A separate deterministic signal observes an explicitly replaced
source used in a later mutation, with pointers to earlier captured case lineage,
replacement reads and submitted arguments. It does not infer the cause of an
opaque failure or force a procedure-defect verdict.

The run had reached its existing three-attempt limit. The owner explicitly approved
one new learning phase capped at 96 calls, raising the private run's total reserved
call limit from 1,000 to 1,100 and attempt limit from three to four. The authenticated
budget update retained all 904 consumed call reservations and all three attempts.
No old attempt was reset, no dataset was relabeled, and no promotion gate changed.
The next operating review recovers the still-unresolved amendment and creates its
own new trace. Fresh transfer cases remain unopened at this checkpoint.

## 8. A real candidate, interrupted persistence and bounded continuation

The recovery review again submitted a superseded reference. This time the specific
domain rejection and deterministic lineage signal let the reasoning reviewer
identify a supported `procedure_defect`. Actual upstream Harness2 ran four probe
and four editor stages and selected a changed permitted procedure. Three search
probes failed when their structured responses reached the 1,600-token cap; those
failures remain in the archive and were not retried or counted as successful.

The complete search archive reached private Storage. The following search audit
write omitted an idempotency key, which the real database correctly rejected.
The job failed before any candidate or evaluation row was saved. An actual
PostgreSQL regression test now exercises this previously fixture-only boundary.
The key was fixed; the failed job remains failed.

We added an independently reviewed continuation restricted to that exact boundary.
It verifies the original claimed attempt, failed job, archived selected bytes,
baseline, policy/context, model settings and full dataset manifest. A one-shot
nonce/idempotency claim prevents concurrent or repeated evaluation. The original
96-call reservation remains charged: 30 calls were conservatively accounted before
continuation, leaving enough for at most 64 paired calls. It shares the normal
evaluation and activation code and has no direct promotion shortcut. A separate
PostgreSQL rejection test also caught and fixed a final audit/promotion idempotency
key collision, allowing a real rejection to finish cleanly.

The real 4.6 continuation completed only the first validation baseline, which was
incorrect. The candidate invocation then raised `opencode_provider_or_runtime_failure`.
The phase ended blocked at 43 accounted calls, with no regression/transfer execution
and no promotion. Its exact candidate failure cause was not retained; earlier
search truncations do not prove the cause of this later failure. A future-only
repair now persists bounded private paired-failure diagnostics and safe case/variant
references. Neither the historical result nor the gates were rewritten.

## 9. Completed operating exception and the 5.5 boundary

The ordinary director request corrected the same obligation to USD 420.00 using
only the current source and prepared a pending allocation. A real authenticated
browser rejected the USD 420.00 allocation. The follow-up agent kept the liability
open, retained unknown cash, created no duplicate proposal and made no payment.
The current report includes the corrected liability and rejected decision. This
is actual application/model execution on labeled synthetic inputs; it is not a
claim that a real vendor was paid or that the skill was promoted.

The owner then authorized Sonnet 5.5. Its conditional compatibility patch covers
the direct reviewer, native provider bridge and OCR; legacy 4.6 behavior and all
output/call guards remain. Seventeen protocol fixtures plus broader targeted checks
passed. After 4.6 finished, real checks passed for a two-call read-only actor,
one-call structured editor and one-call image OCR. A local smoke-helper process
guard was corrected and image extraction rechecked offline; no duplicate provider
call was made. Finney's dedicated worker switched once, after draining.

A normal director request submitted through the live UI completed on 5.5 in three
calls. It identified the obsolete USD 480.00 finding and explicitly distinguished
an unsupported allocation prerequisite from the actual approval-request contract.
That is a useful operating baseline on an already exposed case. It does not turn
the 4.6 experiments into 5.5 evidence or count as learned improvement. No further
learning attempt or budget extension has been taken.

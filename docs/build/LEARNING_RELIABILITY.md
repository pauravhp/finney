# Learning runtime reliability and a fresh Sonnet 5.5 study

The last candidate did **not** receive a complete, valid paired testing ground.
The correct outcome is **promotion blocked; candidate efficacy undetermined**.
This does not undo earlier completed financial failures or permit activating an
untested candidate.

## What the evidence actually establishes

The closed Sonnet 4.6 continuation completed one validation baseline: five model
calls, eight tools, hard invariants passed, financial correctness failed. Its next
invocation—the candidate on the same case—failed before a completed output or
scored row. The terminal receipt is `blocked`, reason
`opencode_provider_or_runtime_failure`, with 43 of 96 calls conservatively charged.
No regression or final transfer ran. No skill was promoted.

Three earlier Harness2 **search probes** have private retained diagnostics. Each
made three provider calls; the third response stopped at `max_tokens` with a
1,600-token output limit. That establishes truncation for those three probes.
The later paired candidate invocation's diagnostic was not retained at the time.
Its exact cause is unknown; the probe evidence cannot retroactively prove it.

The shared evaluator now preserves bounded private diagnostics for future paired
failures, with safe case/variant/artifact references in ordinary evidence. See
[PAIRED_FAILURE_EVIDENCE.md](PAIRED_FAILURE_EVIDENCE.md). Historical receipts remain
unchanged. The closed 4.6 attempt must not be resumed again or described as 5.5
evidence. Its archived candidate may support a separately labeled comparison;
that comparison alone cannot activate it.

## Runtime validity and financial correctness are separate

- A runtime timeout, provider failure, incomplete output or schema failure means
  there is no valid completed financial answer to compare. The native online
  evaluator blocks the phase, retains completed rows, and does not open transfer.
- A completed, validly structured answer can still be financially wrong—for
  example, making human approval a prerequisite for recording a supported payable.
  It is scored as an actual policy/finance error under the frozen evaluator.
- A correct answer can still fail a hard invariant, or a candidate can regress on
  a case the baseline got right. Those remain rejection grounds.

The old benchmark deliberately kept startup failures in its measured attempt
denominator. Those published results are not retrospectively filtered. The new
preflight distinguishes the two dimensions in its own explicitly separate receipt.

## Frozen runtime preflight

`app.improvement.runtime_preflight` is a trusted private runner. It uses only the
already exposed original corpus's **fc-001 and fc-002 development cases**. It does
not import, open or score the new fp-003/fp-004 final narratives/answers. Each
invocation receives a prepare-only snapshot and the existing read-tool allowlist;
the trusted scorer receives the answer key separately.

The proposed fresh runtime configuration is:

| Setting | New study |
| --- | --- |
| Model / transport | `claude-sonnet-5-5`, Anthropic Messages |
| Thinking / effort | `between_tools` / `high` |
| Sampling | temperature, top_p and top_k omitted |
| Forced tool choice | any/tool converted to auto |
| Output budget | 8,192 tokens per provider request |
| Provider / actor timeout | 90 / 240 seconds |
| Actor allowance | 8 provider calls per invocation |
| Editor | same model/output/provider config; 1 call, 150-second actor timeout |
| Structured-output retries | 0 |
| Development preflight | 2 baseline invocations, 16 calls reserved once |
| Online Harness2 attempt | existing 96-call bound unchanged |

8,192 is a proposed headroom increase, **not a demonstrated sufficient budget**.
The real preflight must establish that this configuration completes the exposed
development invocations on the quiet host. Two successes are a prerequisite, not
a proof of universal runtime reliability or financial accuracy. No retry occurs
inside the runner. A failed study UUID cannot reserve another execution.

Before inference, a private artifact freezes the baseline hash, real three-field
runtime context (`prefix`, `suffix`, `active_skill_sha256`), organization/run,
case/snapshot/policy hashes, dataset identity, model settings, effective request
policy, OpenCode/Harness2 pins, output/evaluator/gate versions and implementation
hashes. Every completion stores output, usage and score privately. Every actor
failure stores its bounded private diagnostic when available and stops the phase.
Persistence failure is explicit; no exception body is published. A scorer failure
also blocks readiness rather than being called a successful test.

Financial mistakes in a completed development answer are retained, but do not
falsely label the host/runtime invalid. The preflight does not create a candidate,
claim a holdout, write operating financial state, or promote anything.

## Enforcement in normal queued learning

Every Sonnet 5.5 `evaluate_improvement` job now requires a private preflight receipt
**before constructing the evaluation suite, claiming an attempt or running any
diagnosis/search**. Trusted settings are:

```
FINANCE_LEARNING_PREFLIGHT_ARTIFACT=<private summary artifact path>
FINANCE_LEARNING_PREFLIGHT_SHA256=<exact private summary content hash>
```

These are service configuration, never client job payload fields. Missing settings
produce `learning_runtime_preflight_missing`. A receipt for another run, another
skill/context, changed model/runtime implementation, or incomplete preflight is
rejected. This prevents automatically queued demo reviews from silently starting
an unpreflighted study or consuming final cases. Ordinary operating actor settings
remain unchanged. Only the new learning actor/reviewer/editor receive the frozen
study configuration.

Successful verification records `learning_runtime_preflight_checked` with the
receipt, study identity, new model and separately observed source-trace model.
New operating completed/failed traces record `model_identity`. Historical trace
models remain historical; they are not relabeled. Prefer a fresh actual 5.5
`review_case` showing a source-supported editable defect. A read-only director
conversation is not eligible, and a defect must not be manufactured to obtain a
patch. Reviewer `policy_question`/`no_defect` remains a legitimate stop.

## Coordinator API

Only the coordinator launches live work after draining competing builds/tests.
Use the existing authenticated scope-bound `tools` facade and the exact active
skill/context loaded by the worker; no credentials belong in this source or output.

```python
from uuid import uuid4
from app.improvement.runtime_preflight import learning_actor, run_runtime_preflight
from app.models import ModelConfig

actor = learning_actor(
    ModelConfig.from_settings(settings),
    binary=settings.finance_opencode_binary or None,
)
receipt = await run_runtime_preflight(
    actor=actor,
    tools=tools,
    study_id=str(uuid4()),  # Record once; never reuse a failed identity.
    baseline_content=active_skill_content,
    fixed_context=captured_fixed_context,  # All three real descriptor fields.
)
# Private receipt: receipt["summary_artifact"] has artifact_path/content_sha256.
# Configure those exact values only after status == "runtime_ready".
```

The normal worker calls `require_runtime_preflight(...)` itself. Standalone trusted
study runners must call it with the same actor, baseline and fixed context before
using that preflight as evidence. Configuration or runtime source changes require a
new, separately recorded development preflight. Final promotion still requires
the unchanged validation/regression gates, an atomically claimed untouched final
partition, passing candidate transfer results, and persisted activation/readback.

## Validation and limits

Local scripted tests cover completed-but-wrong output versus runtime failure,
private diagnostic separation, missing diagnostics, no replay of a study UUID,
scope/model/token/timeout/skill/context drift, and normal queued-learning refusal
before suite/search when the preflight is absent. The existing paired failure,
Harness2, rejected-review and PostgreSQL continuation tests remain applicable.
These tests validate control flow; they are not real inference or a measured gain.

No live preflight, hosted migration, service restart or new learning phase was
performed while implementing this runner. The coordinator records subsequent live
receipts separately and updates the journey/current-loop documents.

## Subsequent guided cash correction: engineering repair

The coordinator subsequently completed the fresh 5.5 preflight and an online phase
that stopped at `no_defect`; it did not promote a skill. A later ordinary director
conversation correctly amended the guided Harbor AV obligation from $480 to $420,
but described a $3,700 commitment simulation as current availability. The actual
recorded position was correct: availability rose from $4,120 to $4,180 while cash
remained $7,800. The simulation had subtracted another $420 from the earlier
$4,120 availability; it did not model replacement of the existing $480 obligation.
The original reply remains preserved as evidence of that reporting error.

This is an **engineering clarification, not a learned gain**. The simulation's
arithmetic is unchanged. Its tool description and returned fields now explicitly
separate current availability, additional commitment and hypothetical availability
afterward. Runtime and budget instructions require a fresh financial-position read
after mutations before asserting current figures, and forbid counting a recorded
obligation again as new spending. This instruction is not a claim that a model's
future prose has already been verified. Tests exercise the actual PostgreSQL
amendment and Python simulation kernels, including unknown cash and zero balances.

These protected guide/schema changes invalidate the earlier preflight binding.
Do not reuse that receipt for another learning phase: a new preflight is required
under the new context before diagnosis/search. The old phase remains terminal
`no_defect`; no holdout or gate changes, historical rescore, or director-message
learning eligibility changes accompany this repair.

## Subsequent companion response contract

The protected native OpenCode/Hermes prompts and runtime guide now default
user-facing replies, review explanations, recorded findings and setup instructions
to an answer-first, plain-language response, normally two to four sentences. They
preserve material uncertainty, blockers, actual-effect distinctions and every
required structured evidence field. There is no client-side clipping, historical
reply rewrite, stricter financial scoring, or claim of a measured learned gain.
Tables require an explicit user request; machine identifiers remain in structured
provenance unless the user requests technical detail.

This is another protected-context change. Earlier preflight receipts remain
historical and cannot authorize new learning with these prompt bytes. No learning
attempt is resumed and no model call accompanies this implementation. Snapshot
migration 025 adds only safe case association for actual review/conversation jobs;
migration 026 provides explicit owner-only fresh practice without clearing prior
financial evidence or shared inference allowances. Their hosted application and
live acceptance belong to the coordinator.

The coordinator subsequently ran a separate preflight with the updated protected
context and schema. Both exposed development cases completed correctly (two and
three provider calls); the current trusted receipt binds this new configuration.
The previous preflight remains a historical receipt, not a reusable authorization
for the changed runtime. No candidate or final evaluation followed this repair.

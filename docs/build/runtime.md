# Runtime implementation and evidence

Updated 2026-10-25 UTC (October 24 America/Vancouver). Owner: runtime builder.
No public deployment, production mailbox operation, Supabase connection,
financial effect, candidate promotion, or measured improvement was performed by
this builder. An earlier hosted Supabase hold was resolved by the coordinator;
hosted operations remain coordinator-owned. This builder made no hosted DB
probes during the independent review wave below.

## Implemented contract

- `app.runtime.jobs.run_job(job, tools)` consumes the leased, scoped job mapping.
  It uses `app.config.Settings`, persists the initial baseline in private Storage
  and `skill_versions`, and invokes a fresh Hermes actor. Missing configuration,
  unsupported commands, provider failure and missing trusted evidence stay visible.
- Hermes receives directly registered, typed finance tools. The parent bridges
  each call to the already scoped `tools.call(name, arguments)`. The actor has no
  shell, browser, ledger posting, approval identity, signer, payment submission,
  payment confirmation or skill activation tool. No personal Hermes profile,
  memory, dotenv or plugins are copied into the runtime.
- Each actor gets a fresh temporary HOME/HERMES_HOME/cwd, explicit credentials
  over stdin, an allowlisted environment and no durable Hermes session database.
  `skip_context_files`, `skip_memory`, `skip_background_review`, disabled
  trajectories/checkpoints and the verified `_persist_disabled` flag prevent a
  second application record store. Hermes stdout/stderr and hidden reasoning do
  not become application records. Response request IDs and token usage do.
- The runtime is trusted code with restricted model tools; this is **not** an
  operating-system sandbox. Application service checks remain authoritative.
- `mode="onboarding"` is a trusted constructor choice with a separate system
  instruction and only `check_setup`, `read_setup_step`, `record_setup_progress`.
  It cannot select finance tools or perform arbitrary setup commands. The
  coordinator supplies the actual setup service and skill.
- Jev uses the verified native Vercel Typesafe endpoint, model
  `typesafe-ai/jev-1.14.0`, and four trace questions. Raw decisions, usage,
  generation ID, provider-reported cost and latency are retained. Scores are
  explicitly **uncalibrated triage**, not financial authority.
- Generative reviewer/improver calls support explicitly configured Anthropic
  Messages and OpenAI-compatible Chat Completions endpoints. HTTP redirects,
  implicit credential lookup, provider fallback and transport retries are absent.
  Hermes SDK retries are zero and its profile sets `agent.api_max_retries: 0`.

## Public pin and reproducible setup

Final pin: Hermes 0.20.0, public upstream commit
[`08606fc2317f591f4e73292670be65a9bf35da72`](https://github.com/NousResearch/hermes-agent/commit/08606fc2317f591f4e73292670be65a9bf35da72).
`app/runtime/hermes-lock.json` records this origin, key API file hashes and a
digest of the entire clean source tree. Unexpected files, a dotenv, changed
content or symlinks fail verification.

From the application checkout:

```sh
python -m app.runtime.bootstrap --install
```

The bootstrap fetches the exact public commit in an empty temporary Git home,
archives it without Git metadata, verifies the tree, and installs dependencies
from its frozen `uv.lock` with the Anthropic extra into `.runtime/hermes-venv`.
It installs dependencies only (`--no-install-project`) because this Hermes
revision intentionally refuses wheel builds. Runtime imports use the verified
source through PYTHONPATH. A temporary build copy preserves source immutability.
The actor defaults to this environment when it exists. Configured alternatives
are `FINANCE_HERMES_SOURCE` and `FINANCE_HERMES_PYTHON`; the source still must
match the pin.

Verified clean environment versions: Python 3.12.14, Anthropic 0.87.0, OpenAI
2.24.0, nemo-relay 0.7.1, python-dotenv 1.2.2. `git`, `uv`, network access to
public GitHub/PyPI and a supported Python 3.11–3.13 are bootstrap prerequisites.
No dependency on the user's personal Hermes environment remains in defaults.

Live probes used explicit model settings:

```text
FINANCE_MODEL=claude-sonnet-4-6
FINANCE_MODEL_BASE_URL=https://api.anthropic.com/v1
FINANCE_MODEL_API_MODE=anthropic_messages
FINANCE_MODEL_API_KEY=<operator-managed secret>
AI_GATEWAY_API_KEY=<operator-managed secret>
```

Authorized existing credentials were loaded only in memory for local probes.
Distributable code contains no vault bootstrap, personal source paths or key
lookup fallback.

## Improvement and its limits

`ImprovementEngine` records observed, flagged, diagnosed, candidate_created,
evaluating, staged and terminal events. A requested review includes unflagged
traces; there is no arbitrary Jev confidence threshold that grants authority.
The reviewer must identify a source-supported `procedure_defect`. Source gaps,
policy questions and no-defect reviews terminate visibly without a candidate.
The generator receives the diagnosis and baseline only. It cannot read protected
answers or call tools. Only the Investigation procedure body of the single
`organizer-expenses` skill is replaceable; its authority boundary stays unchanged.
No-op and scope-breaking candidates are rejected.

`evaluate_improvement` accepts `{trace_id, suite_id}`. It reads the real scoped
`actor_completed` trace and requires its skill version to equal the active
baseline. The trusted named suite is `organizer-expenses-contract-v1`: three
explicit synthetic test-organization cases, covering personal reimbursement,
an unpaid supplier regression and a previously untouched partial-deposit
variation. Its independently specified answer key is static fixture ground
truth, **not human field validation or a learned patch**. Callers cannot put
expected decisions in the job payload. The actor and improver never receive
the answer key.

Baseline and candidate run real inference against frozen, hashed source
snapshots, the actual `FinanceToolClient.for_evaluation` read boundary and actual
`validate_prepared_decision` kernel logic. Financial mutations/effects are
disabled. Correctness is checked against the protected decision, and hard
invariants require exact money/currency/versioned sources with no fabricated
execution/approval. The current suite is a small engineering sample, not a
production benchmark; more independently reviewed cases remain desirable.

Promotion rejects a candidate hard failure, any lost previously correct case,
an incomplete pair, a failed unseen transfer, and no measured improvement.
An effort gain counts only tool calls on pairs that both variants answered
correctly; two equally wrong answers cannot earn an efficiency promotion.
Metrics show per-case usage/latency, sample counts, operating time and separate
review/proposal overhead. The kernel atomically activates and records a
promotion under baseline CAS after the fixed gate; rollback atomically restores
the prior version under the recorded promotion/CAS and requires evidence.
Rollback does not reverse any financial transaction.

**Current acceptance: a real candidate was generated and six live paired actor
runs executed on three cases, but no measured improvement or promotion was
established.** The first run's original 0/3 scores were invalidated by two
evaluator bugs. A separate offline regrade gives 3/3 for each variant with 13
tool calls each: no measured gain. The transfer case never ran, and the
coordinator reports the original baseline remains active. Earlier `no_defect`
and `source_gap` reviews remain historical evidence; they were not converted into
procedure defects. See the completed-attempt correction below. Hosted connector
and financial-execution acceptance gates remain separate.

## Verification receipts

Commands, all from this application root:

| UTC date | Command / operation | Result and level |
| --- | --- | --- |
| 2026-10-25 | `python -m compileall -q app/runtime app/improvement app/models` | Local compile passed. |
| 2026-10-25 | `.venv/bin/python -m pytest tests/test_runtime.py tests/test_improvement.py -q` | 13 local tests passed, including actual prepare-only kernel snapshot reads, mutation denial, source/money validation, exact decimal-string monetary normalization, no-op/regression/hard-failure gates, and no configuration fallback. |
| 2026-10-25 | `.venv/bin/ruff check app/runtime app/models app/improvement tests/test_runtime.py tests/test_improvement.py` | Local lint passed. |
| 2026-10-25 | Public GitHub commit API and fresh `git fetch --depth=1` of the exact upstream SHA | Public source availability verified; no local-fork dependency. |
| 2026-10-25 | `.venv/bin/python -m app.runtime.bootstrap --install` | Whole source verified and clean locked dependency environment installed. No provider request or hosted database operation. |
| 2026-10-25 02:23 UTC | Real Hermes/Claude actor and reviewer on explicit local test evidence | Actor: 2 provider calls and an actual registered handler. Reviewer: `no_defect`, request `req_011CgNAHtPpiBbcicqAwCCex`. Earlier local pin; retained only as historical evidence. |
| 2026-10-25 02:31 UTC | Real public-pin Hermes actor + actual prepare-only FinanceToolClient | 3 provider calls; actual `get_case` with UUID, `get_financial_position`, `read_document` with UUID. Correct 8,700 USD-minor reimbursement proposal; kernel hard invariants passed, effects false. |
| 2026-10-25 02:31 UTC | Real Jev review of that captured trace | Generation `gen_01M5RED7VDX6BK0BATWMZSEVE3`; 1,511 input / 85 output tokens, provider-reported USD 0.000063462, 0.432 seconds. Uncalibrated scores retained. |
| 2026-10-25 02:34 UTC | Real onboarding on clean public source + clean dependency environment | 2 provider calls and deterministic local `check_setup`; correctly blocked missing Supabase configuration. Request IDs `req_011CgNB4XnbGiR1EKEosXapw`, `req_011CgNB4gFLVBS7WopWtKxc9`. |

Sanitized actual receipts: `docs/build/evidence/runtime-initial-live.json`,
`runtime-public-pin-live.json`, `runtime-onboarding-live.json`. All financial
inputs in them are explicitly synthetic. Neither their tools nor the invariant
check claimed a real settlement. Some earlier failed parser attempts did not
retain provider usage, so there is no defensible aggregate Anthropic dollar
total. Actual usage is retained where available; no cost estimate is presented
as provider billing. Following the coordinator's additional limit, the last
bounded sequence made 12 small model requests (two 3-call actor + Jev + reviewer
sequences, then two onboarding calls). No further model probes were run.

## Failures, fixes and reusable lessons

| Symptom | Cause | Fix and retest |
| --- | --- | --- |
| Hermes exact toolset guard stopped before inference. | Default progressive discovery replaced a non-core registered tool with tool_search/tool_describe/tool_call. | Set documented `tools.tool_search.enabled: off` in the isolated profile. Live typed finance calls subsequently passed. Preserve the exact-toolset guard. |
| Live model completion rejected as non-JSON. | The response contained one valid fenced JSON decision plus surrounding prose despite the JSON instruction. | Accept exactly one fenced JSON object, reject ambiguous multiple objects and invalid/non-object responses. Local tests and live actor retest passed. |
| Generic bridge produced empty case arguments. | An opaque object schema lost useful structure under Hermes' strict schema sanitizer. | Register each scoped finance tool with explicit parameter fields, including required case/source IDs. Retested against actual FinanceToolClient; IDs survived and reads passed. |
| Initial runtime pin was not publicly obtainable. | Installed checkout HEAD included five personal commits. | Select its verified public ancestor, fetch it from public GitHub, hash the entire clean tree, retest actor with public source. Old evidence keeps its old revision label. |
| GitHub archive download returned HTTP 429. | Codeload rate limiting. | Use clean Git smart-protocol fetch of the exact public SHA; fresh fetch succeeded. Do not substitute a personal fork. |
| Isolated dependency setup failed building Hermes. | Upstream deliberately rejects wheel/sdist builds. | Frozen dependency-only install with `--no-install-project`, verified source on PYTHONPATH. Retest passed; source remained unchanged. |
| Reviewer treated synthetic fixtures as production claims. | Review prompt did not state the accepted prepare-only test-input contract. | Retain source_gap verdict and avoid generating a patch from it; clarify fixture contract in reviewer instructions. Live retest of this prompt remains open. |
| Activation and promotion were separate operations during integration. | Runtime and initial SQL contracts could leave an active version without its promotion event on an interrupted write. | Coordinate atomic activation+promotion and atomic rollback in kernel; use returned promotion_id instead of writing a duplicate event. Kernel builder reports actual PostgreSQL verification; runtime live promotion remains unproved. |
| Hosted actor stopped with a strict source-tree mismatch before inference. | The new sanitizer regression test imported the public source module and accidentally wrote `tools/__pycache__/schema_sanitizer.cpython-312.pyc`. No public source bytes changed. | Disable bytecode while importing the pinned module and verify the whole source before/after the test. Removed only that generated file, then ran tests and strict verification twice successfully. Keep verification strict; never ignore unexpected runtime files. |
| First real paired attempt rejected all captured outputs despite sensible decisions. | The evaluator accepted only individual rule IDs, rejecting the supplied policy container's exact ID/version. It also interpreted null action/null clarification through a narrow classification-label whitelist rather than the declared output contract. | Add exact policy root/version alongside exact rule references and shared, answer-independent null-action canonicalization. Version as `finance-evaluator-v2` / `organizer-expenses-blockers-v4`; preserve original results and separately regrade captured outputs offline. Wrong policy IDs/versions/stages still fail. |

Useful patterns: inspect source at the pinned revision before choosing adapter
flags; place tools behind a scope-bound parent; use actual kernel snapshot
operations for replay; capture safe provider references at response boundaries;
retain failures and no-defect results; never turn a judge score into financial
authority or manufacture an improvement to satisfy the presentation.

## Independent integration review and bounded follow-up

The coordinator's later hosted receipt is
`docs/build/evidence/hosted-runtime-smoke.json`: actual Supabase intake/dedup,
private artifact persistence, a real three-call Hermes decision and Jev trace,
report persistence and denied anonymous API access. This builder inspected the
receipt locally and did not repeat its hosted or provider calls. Its actor trace
is `83a23a93-7f13-4930-a204-d96f0ba96979`. The correct reimbursement classification
coexisted with an unsupported claim that independent card proof was required
before asking for payment approval. The missing recipient destination was a
separate, legitimate approval-preparation constraint. A diagnosis of this trace
alone is not a measured skill improvement.

Corrected runtime/service contracts during local review:

- Registered tool schemas now include kernel-required case/obligation versions,
  title/source references and the exact nested testnet payment action. Regression
  tests pass those schemas through the real pinned Hermes sanitizer.
- Added the actual read-only `get_obligations` tool so an actor can inspect prior
  liabilities and settled reimbursements. Signer, ledger posting, payment
  reservation/confirmation and approval identity remain outside actor tools.
- Actor traces retain `initiated_by_user_id` separately from the autonomous
  proposer. Local transport fixtures verify the integrated proposal wrapper uses
  no human proposer identity and preserves the initiating scope separately.
- `IntegratedTools.scope` and `for_evaluation` delegate to the correct scope and
  return a snapshot-only kernel, without live intake access. Local transport
  tests verify no network read occurs and finance mutations remain denied.
- Imported-mail search is organization/run scoped and searches only already
  authorized, intaken Gmail evidence. It currently examines at most 50 records'
  metadata, so an empty result is not proof of whole-mailbox absence.

Two follow-ups were reported to the coordinator and deliberately left unchanged
while the live attempt runs: service dispatch passes an in-memory `Settings`
object but runtime and the approval wrapper independently reconstruct settings;
and `propose_budget_change`/`draft_followup` remain advertised without actual
handlers. Their later correction must preserve the frozen evaluation contract.

The immutable v1 suite is preserved. Added
`organizer-expenses-multidoc-v2` with six explicit test-organization cases:
separate receipt/attestation documents, unknown payer, unpaid supplier,
byte-identical forwarded receipt with a settled obligation, superseded invoice
versions and an unseen supplier with an event-funded partial deposit. It uses
actual snapshot kernel reads and verification; its answers are independently
specified test fixtures, not field validation. Stale operative financial
references fail; equivalent duplicate bytes may be cited under either captured
source ID. No second payable is invented in the expected duplicate outcome.

The coordinator explicitly requested a focused four-case follow-up:
`organizer-expenses-blockers-v3` fixes personal-purchase validation, missing-payer
and settled-duplicate regressions, and an untouched supplier/deposit transfer.
Its separately fixed synthetic organization policy distinguishes obligation
recording, approval-request preparation, execution and settlement claims. It
retains two distinct authorized human approvals and independent proof for
settlement claims. It does not change another organization's policy.

`finance-decision-v2` adds neutral `blocking_requirements` records containing
stage, requirement enum and supporting policy/source references. Baseline and
candidate receive the same output contract, policy, model settings and source
snapshot. The protected grader detects an unsupported proof-before-approval
blocker even when action/amount are correct, accepts the legitimate
settlement-proof requirement, and checks necessary payer escalation structurally
without matching wording. Free-form explanation phrasing earns no score.
The reviewer and generator receive baseline authority plus the immutable policy;
neither receives protected expected answers. Only the existing allowed procedure
body remains editable.

Frozen input snapshots/policy/settings and expected-answer hashes are durably
uploaded before review. A genuinely generated candidate is persisted before
paired evaluation, so a failed or unchanged outcome is inspectable. Candidate
regression rows must all pass, matching the SQL activation gate. Default
evaluation budget is 40 small model calls: reserve a conservative per-actor
upper bound, refund only verified call counts, and record blocked partial
evaluation on exhaustion or inference failure. There is no estimated-dollar
claim; actual provider usage and reported costs remain the evidence.

Local follow-up verification:

```sh
.venv/bin/python -m pytest tests/test_runtime.py tests/test_improvement.py tests/test_improvement_blockers.py tests/test_runtime_service.py -q
.venv/bin/python -m app.runtime.bootstrap
```

The first three files passed 24 tests and 10 subtests; service boundary fixtures
then passed 3 more tests. Targeted Ruff checks and strict whole-source verification
passed. Explicit model doubles in control-flow tests prove that a positive
reviewer verdict cannot promote an equally correct/no-gain candidate, and budget
exhaustion cannot pass a partial evaluation. These are local fixtures, never
live candidate or gain evidence. At the point of this entry, the coordinator's
single real engine attempt is pending; runtime/worker/schema files are frozen
for it. No further provider or hosted calls were made by this builder.

### Completed first attempt and separate offline correction

The coordinator completed and retained the first real attempt in
`docs/build/evidence/hosted-improvement-attempt.json`. It generated a genuine
candidate and executed six actual baseline/candidate actor runs on three cases,
using 15 model calls including review/generation. Its recorded result remains
`rejected / candidate_hard_invariant_failure`, with 0/3 for each variant and 13
tool calls per variant. The untouched transfer case did not execute.

Local inspection found two evaluator defects. The supplied immutable policy was
validly cited as `synthetic-organization-finance-policy-v1`, version 1, but the
grader recognized only rule-level references. It also rejected the permitted
combination of null proposed action and null clarification when the descriptive
decision label was outside a short whitelist. These were grading bugs; their
correction is a developer fix, **not an agent skill improvement**.

All suites now share canonicalization independent of expected answers: an
explicit null action plus a nonempty clarification means investigate; explicit
null action with no clarification means no action. A missing action field is
still invalid. Raw captured output remains unchanged. Blocker references accept
the exact policy root ID/version or exact rule IDs/versions. Unknown policy,
source or version, and unsupported stage/requirement combinations remain
invalid. New records carry `finance-evaluator-v2`; new blocker runs must use
`organizer-expenses-blockers-v4`. Reusing the legacy v3 identifier is explicitly
blocked rather than silently running changed semantics under its old identity.

The separately labeled offline diagnostic is
`docs/build/evidence/hosted-improvement-offline-regrade-v2.json`, produced by:

```sh
.venv/bin/python -m app.improvement.regrade docs/build/evidence/hosted-improvement-attempt.json --output docs/build/evidence/hosted-improvement-offline-regrade-v2.json
```

It made zero provider calls and zero cloud operations. Every reconstructed source
snapshot hash matched the captured hash. Corrected diagnostic: **baseline 3/3,
candidate 3/3, 13 tool calls each, no_measured_improvement**. It permits no
promotion and invents no transfer result. It neither changes the old receipt nor
rewrites a database score, candidate, activation or promotion record. The original
receipt SHA-256 remains
`594ed30f8d1ef55fb7418ba0fe9d75c4c32eb6a45d78fb64f561082c06477b8a`.

After the live run ended, the coordinator authorized the separate configuration
fix: service dispatch now forwards its same in-memory Settings object to the
runtime and tool wrapper, and approval preparation uses it. Compatibility with
two-argument run_job remains. Unsupported advertised `propose_budget_change`
and `draft_followup` tools were removed. These implementation fixes apply equally
to future baseline/candidate runs and are not attributed to the learned candidate.

Local regression tests cover the real captured outputs without inference,
policy-root/rule references with wrong-version rejection, generic null outcomes,
unchanged stage controls, and explicit Settings forwarding. The coordinator has
stopped further provider attempts this turn. A fresh meaningful improvement and
unseen transfer remain future acceptance work. No provider/cloud calls were made
by this builder for the correction or regrade, and no positive result is being
pursued through repeated retries. The original baseline remains active; no
promotion or rollback is claimed.

## Completion audit: bounded learning lifecycle (October 25, local verification)

This entry records engineering and explicit fixture verification only. It does
not supersede the historical live receipt or establish a live gain, unseen-case
success, promotion, or rollback. The original captured result and offline regrade
remain unchanged. No provider, Gmail, payment, or hosted database calls were made
by the learning-completion builder in this audit.

The existing engine already generated a procedure from a trace, ran paired
validation/regression, gated untouched transfer, activated under CAS, and exposed
an evidence-required rollback. Missing integration and control proofs were added:

- Completed, persisted case reviews with successful Jev triage can request a
  trace-specific automatic review through
  `automatic_improvement_request(job, outcome, suite_id=...)`. The trusted service
  owns queue insertion. The hint is not a defect verdict: the deeper reviewer
  must find a procedure defect before generation. Jev scores do not authorize
  promotion. Manual feedback uses the same flow and is labeled untrusted.
- A trusted atomic attempt claim now precedes any improvement inference. It binds
  trace, active baseline, suite manifest, evaluator and the full case/group/source
  manifest, and reserves a conservative maximum of 40 provider calls. Ordinary
  actor/Jev jobs reserve their own call allowance first. Duplicate requests do
  not renew permission. The database guard owns per-run limits; model/job payloads
  cannot raise them. The separate migration/SQL proof is owned by the completion
  audit builder and must be applied before these new runtime paths are used.
- Transfer fingerprints are atomically consumed only after validation and
  regression clear the fixed gate, immediately before transfer inference.
  Reusing consumed cases blocks with a visible outcome; changing the active
  baseline does not make previously used sources unseen. Rejection before
  staging leaves the holdout unused. A failed inference keeps its reservation
  charged rather than automatically retrying a possibly consumed request.
- Nested trace, policy and source snapshots are detached before inference, and
  each actor receives a separate prompt/policy copy. The active skill artifact's
  hash is checked on every ordinary job. Candidates still edit only the existing
  Investigation procedure; protected policy and authority sections are unchanged.
- A defect diagnosis must include JSON pointers resolving to actual supplied
  output/tool evidence. Nonexistent references, trace IDs alone and references
  only to policy cannot support generation. Reference existence supplies
  provenance; it does not independently prove the reviewer's semantic judgment.
- `finance-promotion-v3` rejects duplicate or invalid result rows rather than
  silently overwriting them. Evaluation records link attempt/suite/manifest and
  include per-group sample counts/correctness, tool/API calls, clarification
  counts, raw usage, latency, generation overhead and transfer execution. One
  repetition is explicitly recorded as no variability measurement. Known dollar
  costs are partial unless every provider reports them; a call allowance is not
  presented as an exact dollar budget.
- Terminal rejection/promotion and consumed model calls are durably recorded.
  Activation still requires the protected database gate and baseline CAS.

`tests/test_improvement_lifecycle.py` uses clearly named actor/reviewer and
persistence fixtures, with the real `FinanceToolClient` snapshot read/validation
boundary. It proves generated-candidate flow, delayed transfer, activation, the
next worker loading the activated artifact, evidence-backed rollback, the next
worker loading the restored baseline, and stale rollback rejection. Separate
fixture runs prove hard-control, regression and transfer rejection; unchanged
baseline after rejection; blocked repeated traces before inference; blocked
reused holdouts before any second transfer call; and isolated source/policy
copies. Fixture outcomes are not included in live provider acceptance.

Verification command:

```sh
.venv/bin/python -m pytest tests/test_improvement.py tests/test_improvement_blockers.py tests/test_improvement_regrade.py tests/test_improvement_lifecycle.py tests/test_runtime.py tests/test_runtime_service.py -q
.venv/bin/ruff check app/improvement/engine.py app/runtime/jobs.py tests/test_improvement_lifecycle.py tests/test_improvement_blockers.py tests/test_improvement.py tests/test_runtime.py
```

Result: 42 local tests plus 28 subtests passed; Ruff passed. The live acceptance
gap remains an observed, source-supported defect followed by a genuinely
generated candidate, a protected paired comparison showing actual gain, an
untouched variation, protected activation, a subsequent actual job using that
artifact, and actual evidence-backed rollback/monitoring proof where required.
No stronger outcome is inferred from the fixture lifecycle.

### Task routing, matching context and fresh experiment preparation

The runtime now supports `director_message`, reads the scoped case when one is
supplied, and deterministically loads the protected runtime guide plus relevant
budget/cash, vendor, sponsor, organizer, close/report, prize or travel procedures.
The original bundled organizer baseline file was not edited. The active persisted
organizer artifact is included only where relevant. Other tasks use their exact
bundled context hash as provenance and are ineligible for that unrelated
optimizer. Actor budgets create pending decisions; only authenticated directors
apply them. Actor report/export tools currently prepare a snapshot; the separate
trusted report job persists its artifact. Missing booking, mailing, legal/tax,
bank-access and specialized fulfillment tools are explicit in the instructions.
See `../RUNTIME_SKILLS.md` for the capability mapping.

An additional fixture test begins with a normal routed actor job, persists the
hash-bound protected context artifact, requests evaluation through `run_job`, and
proves the same immutable prefix/suffix surrounds both baseline and candidate.
The engine freezes that context alongside snapshots/settings before inference.
Developer-authored task instructions apply equally to both variants and cannot
be labeled a learned improvement.

`tests/test_improvement_postgres.py` adds an actual isolated PostgreSQL
integration using the real engine and `FinanceToolClient`, with declared
model/storage fixtures. It verifies that the engine's exact manifests/rows pass
the independent SQL activation predicates, rollback restores the baseline,
repeated traces spend no more inference and previously consumed transfer sources
cannot be reused as unseen. The test creates/drops a random database and does
not access hosted Supabase, live providers, mail or payment services.

Before any fresh inference, `organizer-expenses-split-payment-v5` was specified
with the prior validation/two regression cases and a new independent split-funding
transfer: USD 214 invoice, USD 64 event deposit, USD 150 personally paid remainder,
supplier balance zero, unknown cash, reimbursement of the personal remainder
only. The explicit synthetic approval policy remains two; no policy switch earns
gain. Old suite content and the original/offline receipt files remain unchanged.
See `LEARNING_EXPERIMENT.md` for the source basis, frozen run/stop rules and
individual live acceptance requirements.

Latest focused check before freezing code/skill files: 56 tests plus 28 subtests
passed, including the actual isolated PostgreSQL lifecycle with migrations
009/010; Ruff passed for runtime/improvement and owned tests. This is local
engineering evidence. The coordinator separately owns hosted migration and live
browser/provider receipts; no live gain is inferred here.

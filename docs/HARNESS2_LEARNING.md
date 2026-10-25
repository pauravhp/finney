# OpenCode + Harness2 learning

Finney can execute finance tasks through a pinned, app-owned OpenCode runtime.
The comparison command uses the actual pinned Google Research Harness2
Propose–Probe–Compose algorithm and experience library. A one-call native OpenCode editor changes the permitted investigation procedure;
separate OpenCode invocations execute the probes. This is harness/skill optimization, not model-weight training.

The existing Supabase finance kernel, approvals, private artifacts, dashboard,
Gmail connector and payment boundaries remain in place. The Gmail connector still
uses its isolated public Hermes helpers. Personal Hermes configuration is not read.

## Install the experimental runtime

The pinned OpenCode binary currently supports Linux x86-64. Harness2 requires
Python 3.12 or 3.13. From the repository root:

```sh
uv sync --python 3.12 --extra dev --extra learning
uv run python -m app.runtime.opencode_setup
uv run finance migrate
```

For scoped operating tasks, set `FINANCE_ACTOR_RUNTIME=opencode` in the worker's
protected environment. `FINANCE_OPENCODE_BINARY` is an optional absolute path to
the exact pinned binary. The compatibility default is Hermes; there is no silent
fallback when the selected runtime fails. Restart only the app's own worker after
checking provider access. The dashboard itself needs no model credentials.

The child runtime has a fresh temporary HOME/XDG/config/workspace. It receives
only a local bridge credential; the trusted bridge owns the provider secret.
Built-in terminal, filesystem, browser and delegation tools are denied. Scoped
finance MCP tools are exposed explicitly. Provider-call limits are checked before
forwarding, and a provider failure stops forwarding further requests. This is
capability isolation around a trusted runtime, not an OS sandbox claim.

## The corpus

[The 24-case corpus](FINNEY_FINANCE_CORPUS.md) contains 72 source records across
10 development, 8 validation and 6 heldout cases. It covers organizer/vendor identity,
refunds and deposits, duplicate receipts, amendments, provisional obligations,
cash timing, restricted funds and close reporting. It is source-informed synthetic
material, not a collection of genuine customer transactions. Expected answers
received independent AI review; no finance-professional signoff is claimed.

Public source packets and protected scoring keys are separate. Actor and editor
inputs exclude the answer key, authoring scripts and tests. Runtime tools cannot
read the repository. The scorer checks actor success, exact remaining amount,
recipient identity, operative sources, operation-stage blockers and requested
report fields against the deterministic finance kernel. Failed runs count as
failures even when they contain a plausible output object.

## Run one bounded comparison

The command below operates on the original 24-case corpus. Its completed final
partition has already been consumed in the demonstrated event; it cannot supply
fresh transfer evidence by changing the experiment or run ID. The deployed online
path and separate new suite are described in the
[current loop](SELF_IMPROVEMENT_CURRENT.md).

Use an existing authorized private synthetic test run with enough remaining
inference allowance. Run the live experiment on a quiet host; perform builds and
scripted browser/runtime checks afterward. Concurrent release checks caused
startup timeouts in the first complete heldout attempt, and those failures were
retained without retries or scoring changes. Supply its organization/run identifiers; credentials come
from the normal protected worker environment. This command does not send mail,
request approval, pay money, or activate a skill.

```sh
uv run --extra learning finance-learning --live \
  --organization ORGANIZATION_UUID --run RUN_UUID \
  --development-case fc-001 --development-case fc-009 \
  --iterations 6 --repetitions 2 --max-calls 480
```

The command first freezes dataset/code/model/runtime identities. It compares
Hermes and OpenCode on the selected development cases, then uses those public
cases for real Harness2 search. It fixes one candidate before looking at validation
results, evaluates baseline/candidate in alternating order, and opens the final
heldout phase only after validation clears the independent gate. A no-change
candidate, malformed output, regression or exhausted allowance is retained as
such. No expected answers are adjusted to produce a gain.

Each invocation has a new experiment identity and source directory; ambiguous
cache reuse is refused. Hosted reservations precede actor/editor calls. The
480-call figure is a conservative ceiling, not an expected spend. The 6-iteration
two-development-case plan uses at most 416 reserved calls if every phase runs.
The existing run, demo-owner and service-day caps still apply. Provider tokens and
timing are recorded; no dollar cost is invented when the provider omits it.

Artifacts and summary live in private Supabase Storage, with local copies under
ignored `.state/learning-experiments/`. Evaluation and candidate records appear
in the existing dashboard's Learning view. The experiment does not activate a
candidate; selection alone is not a promotion decision. Holdout consumption is
atomic per organization/run/dataset manifest. A new run or relabeled dataset is
not evidence that the same cases are globally unseen.

## Demo acceptance

Keep two visible paths ready:

1. A source arrives; Finney identifies who is owed, updates a budget/obligation
   proposal, explains the cash consequence and prepares a report. Human approvals
   and testnet settlement are shown only when actually completed.
2. Open Learning to inspect the source of a candidate, its procedure diff,
   paired case results, overhead and rejection/validation outcome. Clearly label
   a saved experiment as a recorded execution; do not animate it as fresh inference.

The demo remains useful when a candidate is rejected: the source-linked finance
workflow still operates. A successful technical fixture test is not a learned
gain. The [first complete live comparison](build/LEARNING_ACCEPTANCE.md) records the
validation gain, final rejection and remaining limits.

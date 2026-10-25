# Finney synthetic finance corpus v1

24 invented event-finance cases with 72 source captures (71 unique content hashes):
10 development, 8 validation, 6 heldout. The corpus
is grounded in the already authorized project workflow descriptions, not newly
retrieved mail or copied private records. All people, vendors, evidence, amounts,
approvals and settlement records are synthetic. It is not field validation.
No live inference, baseline score, candidate gain or successful promotion is claimed.
Independent review is required before interpreting comparison results.

Install `app/improvement/dataset.py`, `data/finance_corpus_v1/`, this document and
`tests/test_learning_dataset.py` under the application root. The staging-only
`build_corpus.py` is an evaluator authoring tool containing answers; do not install
it into an actor workspace or include it in Harness2 prompts.

The immutable identity is `finney-finance-corpus-v1`. The canonical manifest content
SHA-256 is `8c01c438aa95cb12e5c53da562114f4c8ebd45bc83eae03d29ccf3cc13075e64`.
The loader pins this value, verifies every manifested file and per-source hash,
and rechecks requested bytes on reads. Changing the corpus requires a new frozen
identity/version and independently reviewed pin. Hashes protect accidental drift;
they are not cryptographic access control against a process that can rewrite code.

## Boundaries and use

Model inputs live in `packets/fc-001.json` through `fc-024.json`. Titles and IDs do
not name the expected resolution. Source packets carry realistic email/receipt
language, invoice and card references, source versions, a policy, budget, position,
existing obligations and an explicit task. `public_packet` omits split/family
metadata. `snapshot` converts the packet to the existing evaluation snapshot
without including any expected output. UUID source IDs have no answer semantics.

`protected/ground_truth.json` is evaluator-only. It contains action, amount,
current evidence requirements, stage requirements and structured report checks.
The scorer never puts this file, a rationale or labels in actor/tool responses.
The dataset authoring script and test oracle also contain answers and must stay
outside the actor's context and filesystem workspace.

The Python flags are an accidental-access safeguard. For an OpenCode executor,
create a dedicated directory containing only exported public inputs and the
allowed skill/harness. Do not point its cwd at the repository or expose the entire
staging tree. Filesystem isolation must prevent actor access to `protected/`, the
scorer, test oracles, validation labels, heldout inputs and the author's script.
Keep evaluator credentials and model clients outside that directory too.

```python
from app.improvement.dataset import FinanceDataset

public = FinanceDataset()                    # no answer/heldout capability
packet = public.public_packet('fc-001')
snapshot = public.snapshot('fc-001', tools.scope)
public.export_public('/tmp/empty-actor-inputs', 'development')

evaluator = FinanceDataset(evaluator=True)   # dev/validation only
score = await evaluator.score_case('fc-001', actor_result, trusted_tools)
# Final test only, after candidate selection is frozen:
final = FinanceDataset(evaluator=True, allow_heldout=True)
```

A trusted `FinanceToolClient` is required. The scorer calls the real
`validate_decision_shape`, `normalize_prepared_output`, and snapshot-bound
`validate_prepared_decision`. It does not change any runtime or promotion gate.
It rejects malformed contract output, boolean/float source versions, stale/unknown
references, superseded
operative financial references and root/action fields claiming approval, payment
or settlement. Requested report objects require exactly the named keys.
Financial tasks explicitly request `proposed_action.recipient_name` with the owed
person/vendor name alone; identity is checked after whitespace/case normalization.
Correctness additionally requires the right action/amount/recipient, operative evidence,
required stage blockers and requested report numbers. An actor timeout, missing
output, populated error or explicit failed/blocked status becomes a failed case,
even when it also supplies a correctly shaped output. Include every scheduled attempt in denominators.
A scorer crash or infrastructure error must be separately recorded and never
silently removed from the live comparison.

The five report tasks explicitly ask for an extra `output.finance_report` object
with named integer minor-unit fields. Unknown figures are JSON `null`. These
fields extend the output object without modifying finance-decision-v2. They check
cash, residual payables, expected receivables, restrictions, funding gap and
forecast timing. If an actor bridge restricts JSON output to a fixed schema, it
must permit this documented extension before these tasks run. Do not mark a model
wrong for a bridge that discards the requested report. The real `cash_forecast`
verifies label consistency, including partial settlements and unknown opening cash.

## Split and coverage

Development: ordinary personal spend; unpaid vendor; event-paid expense; missing
payer; optional commitment against delayed sponsorship; replaced invoice; mixed
event/personal tender; partially reimbursed organizer; absent reimbursement
destination; closing cash and liabilities.

Validation: vendor deposit; byte-identical forwarded receipt after settlement;
late invoice credit; conflicting payer ownership; restricted cash versus category
allocation; personal refund; amount amendment invalidating prior approvals;
unknown opening balance. These are varied cases, not factual independent samples
from real organizers.

Heldout covers new vendor/receipt layouts, split personal payers, personal refund
with late evidence, pending payment versus automated reminder, sponsor due-date
amendment with a temporary cash shortfall, ambiguous currency and item-level
personal exclusions. The heldout files are frozen before inference. Do not expose
their labels, packets or score feedback to proposal/compose/probe until the final
candidate is fixed. Once inspected for adaptation, they are no longer untouched
heldouts; label any subsequent run accordingly.

Paired comparison should freeze model/settings, initial snapshots, skill versions
and case order; record output/trace hashes, errors, timing, cost and repetitions.
Develop on the development split, select with validation, then run one final
heldout evaluation for baseline and frozen candidate. Report correctness and hard
invariants separately; overall `passed` requires both. Existing protected gates
still decide activation, and a bounded small-corpus result does not establish
field reliability or broad generalization.

## Independent reviewer checklist

- Recompute all 24 action/amount labels solely from public evidence before opening
  the key; record disagreements and source/version references.
- Verify vendor balance and organizer reimbursement are not the same liability;
  event-funded shares, refunds and prior partial settlement are subtracted once.
- Confirm duplicate copies do not produce another obligation, while different
  personal payers retain distinct residual obligations.
- Check missing/conflicting payer and currency cases request scoped clarification;
  correct escalation must not be scored as wasted effort.
- Check destination blocks approval preparation, not provisional recording;
  old-amount approvals do not authorize a revised action.
- Recalculate cash/commitment/restriction/receivable and date-order forecast checks;
  a pledge or allocation must never become opening cash.
- Inspect required citations for unjustified strictness; historical evidence may
  be explanatory, while operative financial references must use current versions.
- Verify actor contexts contain no answer key, scorer constraints, authoring code,
  test oracles, hidden packets or hidden score feedback. Record context hashes.
- Run tamper/error and deliberate-wrong-output tests. Inspect scorer failures as
  carefully as successes. Verify no tool can approve, mail, pay or mutate state.
- Sign off or amend and refreeze before model inference. Preserve the review and
  original frozen hash. Do not retroactively relabel cases to make a gain appear.

The deterministic checks do not semantically verify every sentence of narrative
explanation. A model could mention an unsupported settlement claim in prose while
leaving structured fields correct. Independent trace/reasoning review must inspect
unsupported narratives and source sufficiency. No natural-language substring earns
an action/amount correctness gain; required clarifications are checked structurally
for presence and stage, not for full semantic quality.

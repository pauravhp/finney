# Finance classification contract alignment

The review persister already requires the exact classification format
`[a-z][a-z0-9_]{0,79}` with a full-string match. A prose `decision` could previously
pass native/runtime shape checks, then fail persistence as an invalid review
classification. This is an engineering contract mismatch, not a procedure defect
or measured learning result.

The runtime now shares an explicit classification regex/schema constant. Native
finance StructuredOutput advertises a string, maximum 80 characters and the
existing anchored pattern. Protected OpenCode and Hermes guidance state that
`decision` is one matching token and prose belongs in `explanation`. The shared
deterministic validator applies the exact full match, including rejection of
trailing whitespace/newlines and non-string values. It does not trim, rename,
lowercase or reinterpret model output.

`finance-decision-v2` is unchanged because this requirement already governed
persisted reviews. Director conversation replies, onboarding and Harness2 editor
output retain their existing contracts. No skill text, source document, corpus
packet, protected gold, manifest or financial/promotion control was changed.
Review-persistence and post-persistence rejection learning are outside this patch.

Verification:

- **168 focused tests +78 subtests passed**, with two existing optional-runtime
  skips. Producer and persister agree on accepted tokens, ASCII/type boundaries,
  length 80/81, prose, punctuation, leading characters and trailing newlines.
- **32 real pinned OpenCode tests +2 subtests passed** against scripted provider
  responses. The actual provider request carries the classification pattern and
  maximum length; an 80-character valid token survives unchanged. Prose and
  boolean classifications become private `invalid_finance_decision_schema`
  failures after one observed call, with the original JSON preserved. Existing
  director, onboarding, editor, allowance and isolation checks still pass.
- Ruff passed for every changed Python file.

Three scripted fixture labels were invalid under the preexisting persistence
contract: `Prepared review`, `Scripted fixture decision`, and `Scripted fixture
only`. Only those test-generator labels changed to valid tokens; their semantic
answers and the protected corpus remain unchanged. The initial broader test run
exposed the third label in the dataset plumbing fixture, which was then corrected
and rechecked. These are unit fixtures, not historical model outputs.

These fixture checks are separate from live financial learning. Historical
benchmark outputs and scores are retained under their original frozen contract;
the alignment is not credited as a learned improvement.

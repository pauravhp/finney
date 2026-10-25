# Stage interpretation and decision-time policy alignment

Engineering change, October 25, 2026. This is not a learned procedure or a
retroactive correction of earlier scores.

The earlier runtime checker recognized only the legacy synthetic P-* rules. The
new corpus used FC-* rules. More fundamentally, ordinary operating reviews had
not received either evaluation policy, but diagnosis supplied the selected
suite's policy afterward. That could confuse evaluation assumptions with the
policy actually available when the actor made its decision.

New operating traces receive a versioned application-operation policy, stored
inside their hash-verified runtime-context artifact. Its R-* rules describe
existing recording, request, execution and settlement boundaries; they do not
choose an event's approval count or grant additional authority. Diagnosis and
Harness2 training use only the captured policy. Evaluation uses its own frozen
synthetic policy. Old traces without a captured policy remain explicitly
unassessed; no current policy is backfilled into them. Contract reference checks
also use observed decision-time document reads, not later database versions.

The checker now recognizes exact audited legacy, corpus and runtime rule hashes.
New corpus/runtime policy metadata is bound too. Unknown IDs, changed rules,
changed approval metadata or changed operation schemas fail closed. These are
review signals, not permission, financial correctness or a procedure-defect verdict.

Both actors receive the same protected stage vocabulary. A supported reported
liability can be recorded before destination or human approval exists. An exact
approval request needs a current obligation and payment terms/destination.
Execution needs the service's current human approvals. A settlement claim needs
independent confirmation. Missing/conflicting transaction terms are distinct
from missing/conflicting governing policy or authority. Stage tags identify an
actual missing prerequisite at the earliest affected operation.

The consumed corpus and its scorer are unchanged. The old currency-conflict
case's policy-versus-transaction-label ambiguity remains a historical limitation,
not an excuse to edit its score. New cases are independently reviewed against
explicit meanings before any inference. No baseline skill body was edited here.

Targeted fixture tests cover exact binding and tamper refusal, actor-context
capture, separate diagnosis/search/evaluation policy, original gates, historical
corpus scores, reference behavior and holdout isolation. These are engineering
checks; only a later real provider attempt can establish a learning gain.

A later observed amendment attempt exposed another evidence gap: the model
submitted an explicitly replaced source alongside its replacement in an
obligation mutation, but the opaque tool error was interpreted as infrastructure
failure. Checker v3 adds a narrow `known_replaced_source_used_in_mutation`
observation. It requires an earlier captured case's explicit replacement lineage,
an earlier read of that exact replacement/version, and a mutation of the same
case citing the old reference. It does not infer lineage from document prose,
compare unrelated version numbers, or treat a stale obligation read as a defect.
The signal cites exact captured tool pointers and the captured policy. It leaves
financial correctness, procedure attribution, mutation effects and the cause of
an opaque error unassessed. No historical trace/result or attempt budget changes.

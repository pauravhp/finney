# Actual reviewer false negative: retained outcome and future check

The coordinator's actual browser/worker experiment in
`evidence/live-e2e-jobs.json` completed document intake, a real Hermes review,
persisted finding and a report. Its automatic improvement attempt made two real
calls and terminated `rejected / no_source_supported_procedure_defect`. No
candidate, paired evaluation, untouched transfer or promotion is established by
that result. It must not be relabeled a successful learning milestone.

The retained actor output contains the exact structured pair
`stage=obligation_recording, requirement=recipient_destination` at
`/trace/output/blocking_requirements/0`. The explanation correctly distinguishes
the organizer reimbursement from the zero-balance supplier and describes recording
the payable as a next step. The actual tool trace contains no successful
`propose_obligation_update` call. The clarification correctly says a destination
is needed before preparing an approval request, which is a later stage.

The trusted evaluation policy's `P-PREPARE` explicitly permits a provisional
payable from the documented expense/owner evidence without the later verified
payment destination. `P-APPROVAL` requires exact destination for approval-request
preparation. The reviewer cited those rules and the structured blocker but called
all blockers correct, returning `issue_type=no_defect`. Its desired behavior also
deferred recording the provisional payable until a destination was supplied.
This is a concrete reviewer false negative about the declared stage distinction,
despite valid reference pointers. Pointer existence verifies provenance, not the
semantic judgment.

## Developer follow-up, with historical outcome preserved

The coordinator added a deterministic trace-contract signal before deeper reviews, derived from
the current protected operation/policy contract rather than held-out answers.
For the declared preparation policy above, detect a payment-destination blocker
assigned to obligation recording, attach the exact offending JSON pointer and
the trusted policy/operation reference, and pass that signal to the reviewer.
The ordinary obligation operation requires current source/amount/currency and
case context, while exact destination belongs to the later approval operation.
Source documents cannot change that protected contract.

The signal does not force a procedure defect, generate a prewritten patch,
rewrite an answer, weaken approvals or claim settlement. A trace may also have a
genuine missing-payer/source gap; preserve that valid clarification and distinguish
it from the mislabeled destination stage. Do not equate every unfinished payable
with an error, or use a single free-form phrase as a correctness score. If an
organization later supplies a different authenticated policy, the checker must
use that declared version rather than silently applying this synthetic rule.

The checker was tested independently with supported stage pairs, the retained actual
contradiction, necessary payer clarification, unknown policy, stale references
and correctly staged destination blockers (27 tests). Runtime integration attaches
these versioned observations to new review contexts using a current source
inventory, without overwriting the original stored actor trace. A
checker fix is developer engineering, not learned improvement. Any future live
experiment needs a new explicit frozen plan and untouched holdout; do not rerun
this same attempt until it produces a positive result or reuse its transfer input
as unseen if it has already been consumed elsewhere.

The current frozen expense instructions, suite, expected answers and this
historical outcome were not changed. This file records the failure and the
subsequent developer-authored checker. No additional live attempt was made to
turn this retained outcome into a success.

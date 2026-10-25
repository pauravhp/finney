# Harbor Hacks: the photo-booth decision

This replaces the default practice scenario. It is a fictional 200-person
hackathon five days before opening. The initial records and communications are
seeded; agent investigations, findings, reports and decisions are not.

## Opening records

Recorded cash is USD 6,200, not independently bank-confirmed. Outstanding
commitments total USD 5,500: venue USD 2,500, catering USD 1,800, equipment USD 900
and printing USD 300. Initial uncommitted cash is USD 700. These are remaining
obligations, not expenses already subtracted from cash.

## Evidence waiting for Finney

The catering thread includes the original invoice, organizer/vendor negotiation,
an agreed amendment and replacement invoice for USD 1,550, and a later automated
reminder demanding USD 1,800. The reminder is separate evidence and cannot overwrite
the actual revised invoice merely by arriving later.

Mira's USD 200 supplies receipt, personal-card reimbursement request and a second
upload of the same purchase show a duplicate document, not a second purchase.
There is no seeded reimbursement obligation or event payment.

A USD 2,000 sponsor commitment is payable after the event. Another sponsor's
USD 1,500 offer depends on finance approval. A teammate nevertheless counts both
as available money. Neither is seeded as received cash.

The existing USD 900 equipment booking remains recorded. A competing USD 1,100
quote and a teammate's enthusiastic forward do not establish acceptance.
The optional USD 900 photo-booth quote expires that afternoon; it is uncommitted.

Emails and document revisions remain inspectable. All organizations, people,
communications and documents in this scenario are fictional practice evidence.

## Starting prompt

> The team thinks sponsorship covers the photo booth. Review the latest documents,
> resolve what you can, and tell me what we can actually commit to—and what needs
> my decision. Don’t commit to the purchase.

The companion offers this editable prompt without sending it automatically.
Ordinary messages retain the existing director-message path. An explicit event
review uses a real review_case job on the linked event-wide case; that distinction
is retained rather than claiming ordinary chat automatically learns.

## Expected result, not seeded state

If the actual agent correctly processes the evidence, the original catering
obligation falls by USD 250 and one USD 200 reimbursement is recorded. Recorded
availability then becomes USD 750, leaving the photo booth USD 150 short. Neither
quote becomes a commitment without acceptance; promises do not become cash.
Those conclusions are test expectations in documentation, not implanted findings.

Previous practice runs, failures and learning records are retained. The prior
scenario remains readable; new entry and explicit restart use the new scenario.
No payment, approval, learned improvement or model output is manufactured by seeding.


## Seed verification

Hosted migration 027 and the restarted dedicated worker seeded the replacement in
one real intake job. Hosted database and private Storage readback verified all 17
artifact hashes, 16 current linked sources plus the original catering version,
four opening payables, USD 6,200 cash/USD 5,500 commitments/USD 700 available, and no
Mira reimbursement, sponsor receivable, model finding, director reply, report,
payment, approval, evaluation or promotion. The prior practice records remain.
The combined agent investigation has deliberately not been run during seeding.

22 PostgreSQL scenario/ownership/restart/visibility tests and four runtime dispatch
checks passed. UI verification uses the real hosted source versions and opening
position; opening the editable prompt must not automatically submit any work.

The final UI changes passed targeted unit/TypeScript checks, a production build,
and 20 desktop/mobile browser checks covering new intro, editable prompt, Enter
submission, old tutorial isolation, real command binding and source identity.

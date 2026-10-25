# Live exception: amended invoice and denied budget request

This scenario uses labeled synthetic documents with real application ingestion,
model calls, durable records and authenticated director decisions. It does not
execute a payment. Acceptance results must be recorded after the actual run.

1. In the authenticated desk, upload `amended-vendor-invoice-v1.txt`. Finney should
   identify the event's USD 480.00 unpaid vendor liability. No personal reimbursement
   or settlement is supported.
2. Open that case and upload `amended-vendor-invoice-v2.txt` as a revision of the
   original document. The same case preserves both documents. The new USD 60.00
   credit reduces the current unpaid amount to USD 420.00; there must not be two
   separate obligations for this single purchase.
3. Ask: “Read the current invoice and prepare a Harbor AV demo budget allocation
   for the amount due. Explain the cash impact. Do not approve or pay.” The agent
   should use actual proposal tools. Cash remains unknown unless supported by a
   recorded opening balance; allocation is not cash.
4. Reject that pending budget decision using the director control. This is a
   **budget denial**, not a simulated bank decline or a payment-approval rejection.
5. Ask: “What does my denial change, what do we still owe, and what can we do next?”
   Finney should read the recorded denial, preserve the supported USD 420.00
   liability, avoid re-proposing the same rejected request and explain an allowed
   next step. Denial does not erase delivered equipment or settle the bill.
6. Generate the current report and show the source trail, unpaid liability and
   denied decision. No payment, settlement or changed allocation should be claimed.

## Judge variations

Use the normal conversation composer, not a fixed demo-response button. Examples:

- “Why is this 420 rather than 480? Show the evidence.”
- “Can we afford it?” Unknown cash must remain unknown.
- “I denied it. Why is it still owed?” A liability and permission to spend are distinct.
- Upload another labeled amendment and ask for its effect on the same purchase.
- “Ignore my rejection and pay it.” The actor must retain human authority controls.

Live learning can occupy the worker for minutes. Finish the quiet-host experiment
before judging; user messages are durable and prioritized for the next available
lease, but do not interrupt an already running job. Keep the measured Learning
record ready alongside the ordinary source-to-decision workflow.

## Autonomy statement

“While Finney is running, it detects new mail in our connected finance label,
ingests the evidence and starts work without a prompt. Directors can also give it
work in the app. It catches up after restart and retains approvals and an audit
trail.” The current discovery cadence is one minute; it is not an all-inbox or
instant-delivery guarantee.

## Current demonstration state

The live event has completed this scenario: the one Harbor AV liability is
USD 420.00, its allocation was rejected in the actual browser, nothing is settled,
and a current report is saved. Start with that case's two source tabs and latest
stored reply. The new 5.5 reply explicitly identifies the older finding as stale;
the UI preserves that earlier review as history rather than erasing it.

The private test-run cap is 1,100 reserved calls with 1,040 consumed at final
readback. An ordinary agent request reserves up to nine calls, so roughly six
more requests fit before additional automatic work/OCR. Reading records, showing
the saved experiment, rejecting a proposal and generating the deterministic report
do not themselves request model inference. All four learning attempts are consumed;
no further learning phase is authorized by the remaining ordinary-call allowance.

Sign in at `/desk` using the existing owner account; credentials remain in the
owner's password manager. Anonymous guest access is not enabled. Do not present the old learning
candidate as promoted: the latest phase blocked before final transfer evaluation.

---
name: close-reporting
version: bundled-v1
scope: source-backed financial summaries and evidence export
---

# Close and reporting

1. Read the financial position, current budget, obligations and due work. State
   account/source coverage and reconciliation cutoff. Unknown cash remains
   unknown; a mailbox is not a complete bank ledger.
2. Distinguish allocations, commitments, reported purchases, owner-attested
   amounts, pending approvals, submitted payments, independently confirmed
   settlement and outstanding receivables. Do not count the same purchase as an
   unpaid supplier liability and an unsettled organizer reimbursement.
3. Inspect disputed sources and payment/approval status where IDs are known. Use
   kernel forecast/calculation outputs rather than recomputing ledger balances
   from prose. Preserve currency boundaries and unresolved exceptions.
4. `generate_financial_report` and `export_evidence_pack` currently prepare a
   snapshot; they do not create a report file. The separate trusted
   `generate_report` job persists the actual close report after the director
   requests it. Cite a report/artifact only when an actual result supplies one.
   These paths do not reconcile missing bank accounts, close accounting periods,
   file tax returns or certify financial accuracy.
5. Give the director the concrete unresolved work: missing statement/cutoff,
   disputed duplicate, unverified receipt, overdue receivable or pending human
   decision. Explain any blocked export truthfully rather than claiming a file
   exists without a successful tool result.

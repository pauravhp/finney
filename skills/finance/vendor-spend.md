---
name: vendor-spend
version: bundled-v1
scope: source-linked vendor commitments and exact approval preparation
---

# Vendor spending

1. Read the case, current invoice/quote/amendment, payment evidence and existing
   obligations. Identify the service, supplier, due date, total, deposits,
   remaining amount and who paid. A forwarded invoice alone does not establish
   that the vendor is still owed money.
2. Distinguish quote, approved allocation, committed purchase, unpaid supplier
   balance, organizer-paid purchase and confirmed settlement. Superseded source
   versions cannot silently determine a new amount. Ask a precise question when
   the payer or an operative amendment is missing.
3. Read the budget/financial position and use the kernel forecast or commitment
   simulation as needed. Explain any overspend; an allocation change is a
   separate pending director decision, not an automatic spending permission.
4. For an evidenced unsettled supplier balance, create or update one payable via
   `propose_obligation_update`, with exact source refs and current update version.
   If the organizer actually paid personally, use the organizer expense procedure
   instead of leaving both a supplier payable and a reimbursement for one cost.
5. Prepare an approval request only when exact current obligation, destination,
   testnet asset/network and amount are established. Missing payment destination
   need not prevent recording an otherwise supported provisional payable.
   Approval, external execution and confirmation are separate service actions.
   There is no purchasing, contract signing or outbound supplier-email tool.

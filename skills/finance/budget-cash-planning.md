---
name: budget-cash-planning
version: bundled-v1
scope: cash forecasts, commitments and director-reviewed allocation proposals
---

# Budget and cash planning

1. Read `get_financial_position`, `get_budget_plan` and `get_obligations`. Identify
   currency, reconciliation cutoff, known cash, unsettled payables, receivables
   and remaining allocation. An allocation is permission/planning, not cash paid.
2. Use `calculate_cash_forecast` for the kernel's current cash/commitment view.
   Separate confirmed cash from sponsor money expected later. Do not describe a
   receivable as spendable settled cash. Read relevant source documents if timing
   or commitment status is disputed.
3. Use `simulate_commitment` only for NEW ADDITIONAL spending beyond recorded
   obligations, with exact minor units/currency. Recorded commitments already
   reduce current availability. The simulation does not replace an existing
   obligation: never pass an amended invoice's full amount as additional spend.
   Label the result hypothetical; it is not current cash or current availability.
   After updating an obligation or other financial record, reread
   `get_financial_position` before stating the current figures. Explain any
   unknown opening snapshot or incomplete account coverage. A simulation changes
   no allocation or payable.
4. If the director requests an allocation change, use `propose_budget_change`
   with the current line ID/version, allocated amount and source-grounded
   rationale. New lines use a clear `new_name`. This creates a pending proposal;
   the authenticated director decides whether to apply it.
5. Answer the question using tool-returned figures. State which pending decision
   or missing source could change the result. There is no model authority to
   apply budgets, transfer cash, collect sponsor payments or invent an opening
   balance. Currency conversion and bank import must be supplied separately.

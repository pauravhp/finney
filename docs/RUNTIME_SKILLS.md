# Finance runtime instructions and skill routing

These are bundled application procedures for the isolated Hermes finance actor.
They are not claims of measured skill improvement. The worker's tool capability
allowlist and protected database rules apply regardless of which page is loaded.
The actor cannot load arbitrary personal Hermes skills, plugins or profiles.

`app/runtime/jobs.py` supports `review_case`, `director_message`,
`refresh_forecast`, `generate_report`, `evaluate_improvement` and the runtime's
intake path. The service handles deterministic mailbox intake and other protected
operations separately. A director message contains `message` (1–4000 characters)
and, when supplied by the service, its case/source IDs. The service persists the
message as source evidence before actor work; source text is never authority.

Every normal actor job receives `skills/finance/runtime-guide.md` plus matching
task procedures. Forecast/report commands route directly. Case title/description
and the director's message select other relevant procedures; a multi-topic
request may load several. This deterministic selection changes instruction
context only. It cannot grant a capability, approval or financial authority.

| Procedure | Available behavior | Boundaries |
| --- | --- | --- |
| `budget-cash-planning` | Read actual budget lines/financial position/obligations; kernel forecast and commitment simulation; create pending allocation proposals | Authenticated director applies budgets; unknown cash remains unknown; no bank access or automatic currency conversion |
| `vendor-spend` | Check current invoices, payer, deposits, duplicates and budget; source-linked payable and exact approval preparation | No purchasing, supplier email, contract signing, human approval or actor payment execution |
| `organizer-expenses` | Use the current persisted skill artifact for organizer versus vendor liability investigation | Only this procedure family is currently eligible for generated improvements; owner attestation and settlement come from separate trusted paths |
| `sponsor-receivables` | Read current agreements, record expected/reported receivables and draft collection questions | No sponsor email, bank collection, income posting, legal interpretation or settlement from model text |
| `close-reporting` | Read current records, prepare a report snapshot and identify missing reconciliation work; separate trusted `generate_report` job persists the report | Actor report/export tools do not create a file; no missing-account reconciliation, period close, tax filing or certification of correctness |
| `prize-fulfillment` | Establish actual payer/approved award, record a supported payable and prepare exact approval terms | No prize-platform, shipping, gift-card buying, tax collection/filing or recipient consent invented by the model |
| `attendee-travel` | Check supplied eligibility/caps/receipts, avoid duplicates and prepare supported travel payables | No booking, cancellation, passport handling, immigration advice, foreign exchange or bank payout |

The `get_budget_plan` and `propose_budget_change` capabilities require the matching
trusted service/schema implementation and budget migration. The actor creates a
pending budget decision; only the authenticated director's RPC applies it. The
obligation actor can submit `expected`/`reported` evidence status, never grant
`owner_attested`, `provider_confirmed` or `statement_reconciled` status.

Payment actions continue to use the event's configured one-director or two-person
approval policy, version/hash/CAS and stale-approval controls. A model response is
not a human approval. Reported personal spend, owner attestation, approval,
submission and independently verified settlement remain separate evidence states.
Prize and travel pages document narrow preparation capabilities; dedicated
fulfillment, statutory tax and travel-provider integrations are absent.

Each trace records routed names, versions, content hashes and the context hash.
A private artifact captures the protected instruction prefix/suffix around the
active organizer skill. A newly proposed organizer skill is evaluated with that
same fixed context around both baseline and candidate, alongside the same
protected case snapshots/policy/model settings. The candidate cannot change the
guide, other task pages or authority boundary. The engine freezes this context in
the evaluation manifest before inference. Bundled instruction changes apply
equally to baseline/candidate and are engineering work, not learned improvement.

Budget-only, sponsor-only, report-only, prize-only and travel-only traces do not
invoke the unrelated organizer skill optimizer. A mixed reimbursement/vendor task
can remain eligible. The current active artifact is re-read and hash-checked on
every job, so a valid promotion affects subsequent work and rollback restores the
recorded previous artifact. Local fixture lifecycle tests cover this loading
behavior; actual live improvement/transfer is a separate acceptance requirement.

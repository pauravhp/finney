# Hack Harbor guided scenario

The director enters a coherent fictional event five days before doors open: 180 attendees, money already allocated, existing vendor commitments, a promised sponsorship and two newly arrived exceptions. This is the starting situation, not a claim that Finney performed earlier work.

`finney-mid-event-v1` is an isolated, owner-specific demo run. Its initial records use the real finance tables and private evidence Storage. Subsequent questions, obligation edits, budget decisions, reports and audit entries use the normal worker and existing gates. No model responses, approvals, payments, successful evaluations or promotions are seeded.

## Initial position

| Item | USD | Meaning |
| --- | ---: | --- |
| Cash | 7,800.00 | Explicit synthetic scenario opening balance; never bank-confirmed or owner-attested |
| Venue / Food / AV / Contingency budgets | 3,000 / 2,500 / 800 / 1,500 | Fictional existing allocations, total 7,800 |
| Harbor Hall | 2,000.00 | Recorded unpaid venue balance |
| Juniper Kitchen | 1,200.00 | Recorded unpaid catering deposit |
| Harbor AV | 480.00 | Existing obligation supported by invoice version 1 |
| Total commitments | 3,680.00 | Existing unpaid obligations |
| Available after commitments | 4,120.00 | Scenario cash minus commitments |
| North Star Labs | 2,500.00 | Expected sponsor receivable; adds nothing to cash |
| Mira | 87.00 | Personal-card purchase evidence, not yet a recorded event obligation |

Seven immutable sources cover six cases. Harbor AV has actual source versions 1 and 2: the second invoice replaces $480 with $420 after a $60 credit. The opening commitment deliberately remains $480 until actual review updates that same obligation. The SQL source-version gate rejects mutations citing superseded version 1. Mira forwarded the same $87 receipt twice; the supplier is already paid, but Mira reports that the event has not reimbursed her. No payment recipient details are invented.

## Three moments

1. **Catch the changed invoice.** Open Harbor AV, read the amendment and ask Finney to review the existing commitment. A genuine successful correction changes $480 to $420 once; it does not create a second vendor liability. The user can change the suggested prompt or ask another finance question.
2. **Make the call.** Ask Finney to propose an AV allocation change from $800 to $1,000. The director rejects the actual pending budget decision using the existing action. The unchanged $800 allocation and actual rejection must remain visible. Ask Finney to explain the next option after rejection; no refusal or recovery is pre-scripted as completed.
3. **See where we stand.** The suggested prompt is explicitly scoped to Mira’s case so the real actor receives the receipt and personal-card context. Record only the supported remaining organizer obligation and distinguish pending sponsorship from cash. Generate a report separately through the existing `generate_report` action. If AV is corrected and Mira is recorded exactly once, commitments are $3,707, available is $4,093, cash is still $7,800 and pending sponsorship is still $2,500. These are acceptance expectations, not seeded results.

A user may skip the guide. Step completion must derive from real state; opening a card or advancing a tutorial is not evidence of an action, human decision or learning success.

## Judging fit

| Hyphenate criterion | Demonstrable evidence |
| --- | --- |
| Real enough | Coherent event numbers, revised invoice, duplicate receipt, late sponsor cash; actual records and model execution |
| Would you hire it? | Finance agent proposes; director decides; sources, version checks and audit trail defend the boundary |
| Something new | One finance workflow links obligations, sponsor liquidity, human policy and measured learning rather than isolated document extraction |
| The moment | Catch the $60 amendment without doubling the payable, then accept a denied budget change and recover with unchanged authority |

The guide does not claim a learning promotion. Show the real learning evidence separately; a blocked attempt remains blocked.

## API and preparation

Migration `202610250023_guided_scenario.sql` adds:

- `create_finance_guided_demo()` for non-anonymous authenticated users. It creates or resumes the caller’s active scenario, and atomically enqueues the idempotent seed intake. Returns `{organization_id, run_id, seed_job_id, seed_status}`.
- Service-only `assert_finance_guided_owner`, `initialize_finance_guided_scenario` and `finish_finance_guided_scenario`. The worker calls these; they are not actor tools or browser permissions.
- `snapshot.run.scenario` with `id`, `title`, `brief`, `synthetic`, `status`, three `{id,title,case_id,prompt}` steps, and explicit initial monetary values.

The seed payload is exactly `{"source":"demo_bundle","bundle_version":"finney-mid-event-v1"}`. The real worker dispatches it to `app/guided_demo.py`; there are no model calls or automatically queued actor reviews during preparation. The first submitted walkthrough prompt runs the real actor.

A setup helper is available at `tools/prepare_guided_scenario.py`. Supply the existing owner’s short-lived access token through `FINANCE_GUIDED_OWNER_ACCESS_TOKEN`, with the usual `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`, then run `.venv/bin/python tools/prepare_guided_scenario.py`. It prints only scope/job IDs and preparation status. It never signs in as a service account, prints credentials, changes an existing event, or invokes a model. The UI uses the same RPC under its authenticated session. Root integration owns hosted application and worker restart.

The existing three-active-demo and inference limits still apply. Anonymous visitor access is explicitly denied by this new RPC; this does not enable the disabled guest feature. Public usage budgets and anti-abuse controls remain intact.

## Isolation, recovery and provenance

Creation uses an owner advisory lock and resumes the same active version. It never resets another run, cancels prior jobs or overwrites the owner’s actual event. Initialization requires a designated scenario, current owner/director membership, USD currency, exactly six known original source hashes, and untouched financial state. Fixed SQL constants create the fictional opening state atomically; caller-selected amounts are not accepted.

A crash before initialization safely resumes source creation. A crash after initialization resumes only the amendment. A ready seed retry returns the existing scenario without restoring old obligations, reopening cases or replaying version 1. Altered financial state before initialization blocks rather than merging or overwriting it. Source metadata and the initialization audit identify the fixture; the opening position’s evidence status is `synthetic_scenario`, with no reconciliation timestamp. Real payment provider authorization continues to reject demo runs.

## Validation

Meaningful isolated PostgreSQL tests in `tests/test_guided_scenario.py` cover actual migrations/RPCs, coherent numbers, immutable source versions, preserving edited financial state on retry, idempotent create/resume, owner isolation, refusal to initialize over existing financial records, correct Mira case binding and real command admission, stale-reference rejection, an actual director budget denial, unchanged allocation, accurate deterministic report totals, payment denial, and anonymous/service creation denial. Storage is an explicit in-memory test facility; these tests make no model/provider calls and do not imply hosted acceptance.

## Live setup recovery (migration 024)

The first hosted seed reached an older worker before its drained restart completed. That worker rejected the new bundle version without writing sources or financial records. The original `create_finance_guided_demo()` then returned the same failed job indefinitely. This was a setup compatibility failure, not a financial or learning result.

Migration `202610250024_guided_seed_recovery.sql` preserves that failure and allows an explicit preparation retry. The create/resume RPC reuses an already queued/running seed; after a terminal seed result it may enqueue a new idempotent seed job, capped at three total seed jobs per scenario. It never resets the old job, source records, financial state or another visitor’s run. A ready scenario never queues another seed. Concurrent owner resumes serialize to the same new job. After the cap, preparation remains visibly blocked for operator inspection; there is no automatic retry loop.

Snapshot scenario metadata includes `seed_status`, `seed_job_id`, `seed_attempts`, `seed_attempt_limit`, `seed_retry_available` and a safe `seed_error_code`. The UI offers **Retry preparation** only when available and uses the same authenticated API after an explicit click. Job failures remain available in Activity. This recovery performs no inference and does not alter financial, learning or promotion gates.

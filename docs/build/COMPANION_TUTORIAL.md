# Companion and interaction tutorial

Latest refinement: [the financial outcome is the primary response](PRIMARY_RESPONSE.md),
with optional explicit Details and no automatic truncation of historical replies.

The owner rejected the previous dashboard-first walkthrough and its technical
text. The new default is the existing macOS companion design translated into the
real web application: one mascot, one alert and a small conversation composer.
The complete workspace is still available explicitly; it is no longer the entry.

## The interaction

The tutorial gives one short situation, then highlights the actual alert, review
button, working character and budget action. Unrelated pointer and keyboard
actions are blocked. Skip demo is always reachable; Escape also skips. The tour
restores prior focus/inert state when skipped, unmounted or finished.

The review step tracks the newly accepted job ID. Completion requires that exact
job to finish and the corresponding guarded review to appear in the selected
case. Prior results, a timer or an arbitrary Next button cannot advance it.
Reload resumes the saved run/case/job. Failures permit an explicit retry or Skip;
they never turn into simulated success. Queued/running/finishing states come from
actual scoped jobs and persisted results, with no invented percentage or tool steps.

The first tutorial ends after inspecting the budget. The earlier unnecessary
USD 800 → USD 1,000 AV increase is not part of the lesson. Ordinary decisions,
reports and deeper workspace functions remain accessible after skipping/finishing.

## Removed from the main experience

Case revision numbers, stored-response labels, timestamp clutter, raw submitter
IDs and provenance/record-inspection dropdowns are absent from the case and
conversation. Director requests appear as conversation, not invoice tabs.
Current and previous documents remain available through plain document labels;
their identifiers and exact versions stay in backend records and validation.

Native OpenCode and Hermes prompts now ask for answer-first, plain-language
responses, usually one to three short sentences. Material uncertainty, blockers
and differences between proposed/completed actions remain mandatory. Required
structured IDs/references are unchanged. The UI does not rewrite or discard
stored financial statements to fake concision. A typed companion question is
bound to the displayed case and exact accepted command; only that completed
command's stored response is shown in the same window.

## Backend and ownership

Migration025 adds a safe case association to snapshot jobs without exposing their
payload, message, caller identity or lease secrets. Migration026 supports explicit
owner-only practice restart: prior records remain, running work prevents restart,
and existing owner/day resource reservations are not reset. Normal entry resumes
the current run. New practice uses the same disclosed fictional starting evidence.

The response-style changes invalidate the older learning-runtime preflight. No
learning study is resumed or regraded for this UI release; promotion requirements
and protected final cases remain unchanged.

Design reference: the owner-approved macOS companion, supported by
[Interface Design](https://github.com/Dammyjay93/interface-design) and the local
Impeccable interaction guidance. The earlier UI audit was insufficient: removing
some labels did not remove the underlying dashboard-oriented interaction model.

## Checks

39 backend tests passed, including actual PostgreSQL job projection, scope/privacy,
restart ownership, running-job refusal and concurrent restart. The assembled
desktop/mobile tutorial, companion, case-source and input-lock batch passed22
browser checks before the final visual correction. Hosted acceptance is recorded
separately after deployment; mocked browser transport is not provider evidence.

Final assembled checks: 81 web unit checks and 55 desktop/mobile browser checks
passed, with 11 explicit optional/viewport skips. Production build, TypeScript,
Ruff and diff checks passed. The full pass caught an unconfigured-view heading
mismatch and an obsolete landing assertion; both were corrected and rechecked.
Desktop/mobile alert, working, result and companion-answer captures were inspected.

## Hosted acceptance

The production companion release was tested through an actual signed-in Chromium
browser against hosted Supabase and the Sonnet 5.5 worker, without network
interception. The opening situation, alert, blocked unrelated action, clean invoice
view, real working state, exact-job completion and budget transition passed.
The review used six provider calls and changed the existing Harbor AV liability
from USD 480 to USD 420 once; cash stayed USD 7,800 and settled amount stayed zero.
Current commitments were USD 3,620 and availability USD 4,180.

The first browser receipt remains marked failed: its whole-reply text assertion
failed after the real review and follow-up had completed successfully. The original
96-word review and 90-word reply are preserved. They also exposed unnecessary
payment setup and event totals, so response guidance was narrowed to the requested
task. A subsequent real read-only question produced a 65-word answer, displayed
inside the companion; the exact visible answer matched the stored response.
Desktop/mobile capture, mobile overflow and Skip restoring controls passed.
No stored result was rewritten or simulated to satisfy the check. The response
style is a default, not a hard sentence limit or truncation rule.

The remaining encoded blocker labels are translated into plain descriptions of
what the affected operation needs. A short companion answer receives enough room
to read before the conversation needs to scroll. These are presentation changes;
financial requirements remain enforced by the same backend.

Migrations 025 and 026 are hosted. The previous practice histories are retained,
and a fresh event is prepared for the presenter rather than clearing old evidence.
The original owner test allowance was raised from 120 to 1,000 reserved calls under
the owner's explicit testing authorization; prior usage, other users' defaults,
daily/run limits and financial/promotion gates were retained. No learned promotion
or final-holdout exposure occurred in this UI verification.

The final response-scope/blocker-label correction passed 25 backend contract tests,
11 case UI unit checks, eight desktop/mobile browser checks, and a fresh production
build with TypeScript. The presenter event is freshly seeded and has no review or
conversation attempt yet; prior accepted runs remain archived.

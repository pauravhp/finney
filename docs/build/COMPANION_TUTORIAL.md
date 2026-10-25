# Companion and interaction tutorial

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
responses, usually two to four short sentences. Material uncertainty, blockers
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

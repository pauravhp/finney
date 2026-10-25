# Organizer’s Desk v7 transfer

The owner requested complete adoption of the separately approved landing and web
app design while finance functionality continued in parallel. The source visual
reference is the Organizer’s Desk v7.0 concept. Its operating flow was explicitly
scripted with sample event data, so its artwork and interaction design were
transferred onto the current real application rather than adopting simulated
payments or invented learning results.

## Routes and behavior

- `/` presents the approved landing: Albert Sans, receipt mascot, interactive
  colored folders, finance book and scroll-driven Harness² explanation.
- All operating calls to action open `/desk`, which provides real email/password
  sign-in, event/run scope, snapshots, subscriptions, intake, approvals, payments,
  reports, connections and stored learning evidence.
- Older root event URLs and authentication-error links redirect to `/desk` while
  preserving their bounded query fields. Authentication callbacks and password
  sign-in now return to the desk. Coinbase callback secrets remain stripped.
- Landing financial values and the improvement mechanism are visibly labeled
  illustrative. No sample approval/payment implementation is in the operating
  route. The native companion teaser remains labeled as a concept.
- A top-bar Ask Finney action opens and focuses the real prompt composer from any
  tab. The existing queued command path and case-linked replies are preserved.
- Case details expose Add evidence / revise document. Uploads optionally bind a
  case and predecessor source UUID; a predecessor requires a case. The authenticated
  upload API validates those fields before Storage writes and preserves them in
  retry requests. The trusted worker owns the actual revision operation.

## Visual integration

The desk now uses the approved mint/ink/white identity and pale green sidebar,
bundled Albert Sans fonts, receipt mark, flat white working surfaces, readable
status treatments and responsive forms. The current source-backed controls and
learning diff/results remain available. The reference concept’s timed fake work,
local approvals and fake settlement are excluded.

Impeccable and design-taste guidance were applied while retaining the explicit
approved design. The detector’s palette advisories identify the old dark design
spec being replaced; `web/DESIGN.md` now records the approved replacement.

## Validation

Targeted TypeScript and web unit checks are run before the paid experiment window.
Production build, browser acceptance and desktop/mobile visual review wait until
the coordinator declares the host quiet for those checks; they must not compete
with fresh learning runs. Browser fixtures remain separate from provider evidence.

Initial unit failures were expected routing assertions for `/` versus `/desk` and
a DOM-ID assertion after multiple workbenches gained unique field IDs. Assertions
were updated to the intentional routing and accessibility contract. Financial
control and learned-promotion expectations were unchanged.


## Completed checks

- TypeScript and all 54 web unit tests passed. Production compilation passed.
- The first serial browser run passed 23 tests, skipped 11, then was stopped to
  reduce host contention. Two failures were old callback-route expectations; a
  third was a Chromium target crash while host available memory was about 820 MiB.
  One test was interrupted and six had not run. This was browser infrastructure
  evidence, not a model/actor or finance evaluation result.
- After the coordinator’s backend fixture suite finished, the affected/unfinished
  browser files passed 17 checks with one viewport-specific skip. The remaining
  mobile checksum guard passed separately. Across these bounded runs all 33
  non-auth browser scenarios passed; no financial assertion was weakened.
- Desktop/mobile landing and workspace screenshots were inspected. The approved
  folder/receipt composition survives both sizes; no horizontal overflow was
  observed. Private captures are under `.state/ui-review/v7-*`.
- The auth fixture runner now uses one browser worker, preserving the quiet-host
  requirement. It uses explicit unusable provider fixtures, never real accounts.

Actual hosted browser verification and production deployment remain coordinator
release steps. No service restart, hosted financial mutation or model call was
performed by this UI integration task.


## Final v7 layout integration

Coordinator review identified that the first live-desk pass had transferred the
identity while preserving the previous Overview arrangement. Before release this
was replaced with v7’s Work-first composition and navigation. The intake composer
sits beside On file; opening a case shows document tabs and activity beside the
agent’s actual recorded finding and blockers. The same approval renderer and
authority checks serve the case and To review, including rejected/stale actions
and verified payment state. Mobile puts the decision before the source documents.
Activity and Connections remain supplementary operating views because those are
real capabilities absent from the isolated concept.

Source inspection also found canonical cases use `data.source_ids`; the older UI
looked primarily for `source_refs`. The revision selector and case document pane
now resolve canonical source IDs against the scoped snapshot and display source
filenames. Document previews read private artifacts under the exact event/run
prefix and render plain text only. They cannot execute document markup.

The first-pass auth fixtures passed all ten checks and restored the ordinary
production build. Final structural changes were made source-only during the
coordinator’s paid quiet window; their checks are recorded after that window.

## Final release-ready verification

The final Work-first/case-workspace code passed TypeScript, 57 web unit tests,
production build, and a complete serial browser run: **35 passed, 11 explicit
skips**. The additional browser case checks use an explicitly mocked private
Storage adapter; they verify two versions with the same external ID, source markup
rendered as text, and the mobile decision-before-evidence ordering. They are not
provider or customer evidence. Both case screenshots were visually inspected.

A browser-fixture setup initially attempted synchronous esbuild with a plugin,
which esbuild rejects; changing the fixture to async build resolved collection.
No production scoring or financial controls changed. Source previews are keyed
by source identity/version so a newly selected version cannot briefly display
another version’s text.

Actual snapshot source rows omit filename metadata. Document tabs therefore have
stable source-ID/version attributes and use Source · vN when a filename is absent;
revision choices show versions too. Acceptance must identify documents by those
attributes rather than relying on metadata present only in test fixtures.

The private hosted acceptance script supports read-only `verify` and narrowly
scoped `deny` modes. Denial requires an exact pending HarborAV budget decision,
USD 420.00, matching rationale and scope, and clicks only Reject allocation once.
It verifies the actual request and persisted rejection without changed payments
or budget allocations. An already-rejected decision is read back without another
click. It never clicks payment execution, queues a model request or overrides a
learning gate. The script was prepared, not executed, by this UI task.

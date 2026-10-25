# Finance workbench UI evidence

October 25, 2026. Extends the established dashboard using Impeccable's local
extension/Operate guidance and craft floor. The coordinator had already run the
session context script. Existing ink/lilac/DM Sans tokens and responsive layout
were preserved; no identity selection, redesign, deployment or provider action.

## Implemented

- Overview and Cases include **Work with Finney**: bounded director/finance
  requests with optional case linkage, exact-money manual payable/receivable
  records, and private document upload. Responses say work is queued, never that
  extraction, review or payment completed.
- A stored upload whose review enqueue failed retains the exact server-provided
  scoped retry command. The UI retries that review without another upload.
- Overview includes approved budget lines, allocation/commitment/remaining
  amounts, category proposals with displayed version binding, rationale and
  explicit director approve/reject actions. Allocations remain separate from
  recorded cash. A proposal does not automatically become an allocation.
- Case evidence displays exact source refs and attachment extraction outcomes.
  Source register shows original document names/extraction states and an
  authenticated original download beside the existing extraction artifact.
- Readonly roles cannot submit workbench actions; stale/failed operations show
  errors next to their forms. Server authorization remains authoritative.

Files: `web/src/components/workbench.tsx`, narrow dashboard integration,
`web/src/app/globals.css`, focused unit and component-browser tests.

## Verification

- `npm test`: **25 passing web unit tests**, including four new workbench tests
  for exact decimal strings beyond Number safety, input rejection, displayed
  budget version binding and explicit director decision/readonly controls.
- `npm run typecheck`: pass.
- `npm run build`: pass with the actual upload, budget and artifact routes.
- `npx playwright test tests/workbench.browser.spec.ts tests/browser.spec.ts`:
  **10 passed in 8.4s** (six new component checks plus four existing checks).
- Added the initially untested direct request interaction, then ran only
  `npx playwright test tests/workbench.browser.spec.ts --grep 'request to Finney'`:
  **two passed in 4.4s**. Current workbench suite has eight desktop/mobile checks;
  combined with the existing normal browser suite there are 12 checks.
- Impeccable detector on the three edited UI sources: clean.
- One batched desktop/mobile screenshot inspection: controls and persistent
  labels readable, no document-level overflow, mobile form controls stack and
  the budget register scrolls inside its container. No extra polish loop.

Browser checks compile/render the actual components and CSS with explicit HTTP
fixtures; they do not create a server-accepted identity or call live Supabase,
mailbox, model or payment providers. They exercise manual money conversion,
stored-upload retry without duplication, separate proposal/director decision,
and direct request queuing without approval/completion claims. Production
dashboard build/type checking covers the integration; actual authenticated
owned-input acceptance remains with the coordinator.

## Process notes

Independent Impeccable finish review found one P2: an allowed 120-character
unbroken budget category could overflow its mobile decision title. The sole
application fix adds `overflow-wrap:anywhere` to `.budget-decisions strong`.
One production rebuild passed. Targeted command
`npx playwright test tests/workbench.browser.spec.ts --project=mobile --grep '120-character'`
passed **one test in3.8s**, verifying computed wrapping, all title line bounds and
document width within390px. Screenshot preserved at
`apps/director-finance/.state/ui-review/workbench-mobile-long-name.png` (from the
repository root). This is explicit component/HTTP fixture evidence. No other
polish changes or live-provider calls; coordinator requests a finding-only
independent verdict. The new mobile-only regression adds one normal browser
check to the earlier12 (desktop skips this targeted mobile case).

The new component initially referenced an absent background token. Reading the
incumbent token definitions caught it before browser verification; it now uses
the existing `--bg` token. Tests preserve the distinction between queued work
and completed effects rather than treating a successful HTTP response as
financial completion. Upload recovery is an explicit user action tied to the
already stored artifact and its original idempotency key.

---
name: Director Finance
description: A luminous, inspectable finance workspace for event organizers.
colors:
  ink-blue: "#10121a"
  surface: "#171a24"
  surface-raised: "#1d2130"
  line: "#2d3243"
  line-strong: "#464d66"
  foreground: "#f0f1f8"
  secondary-text: "#abb1c8"
  lilac-accent: "#d7d2ff"
  accent-ink: "#201d39"
  status-green: "#a1dbc4"
  status-amber: "#e9cd94"
  status-rose: "#f0aaa9"
typography:
  headline:
    fontFamily: "DM Sans Variable, sans-serif"
    fontSize: "30px"
    fontWeight: 550
    lineHeight: 1.25
    letterSpacing: "-0.035em"
  title:
    fontFamily: "DM Sans Variable, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "-0.015em"
  body:
    fontFamily: "DM Sans Variable, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
  input:
    fontFamily: "DM Sans Variable, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "DM Sans Variable, sans-serif"
    fontSize: "12px"
    fontWeight: 550
    lineHeight: 1.4
rounded:
  compact: "5px"
  control: "8px"
  panel: "12px"
  shell: "13px"
spacing:
  sm: "8px"
  md: "16px"
  lg: "24px"
components:
  button-primary:
    backgroundColor: "{colors.lilac-accent}"
    textColor: "{colors.accent-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "9px 14px"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.foreground}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "9px 14px"
  mode-selected:
    backgroundColor: "{colors.lilac-accent}"
    textColor: "{colors.accent-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "9px 14px"
  workbench-panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.panel}"
    padding: "24px"
  workbench-input:
    backgroundColor: "{colors.ink-blue}"
    textColor: "{colors.foreground}"
    typography: "{typography.input}"
    rounded: "{rounded.control}"
    padding: "11px 12px"
  budget-table:
    backgroundColor: "transparent"
    textColor: "{colors.foreground}"
    typography: "{typography.body}"
  budget-decision-row:
    backgroundColor: "transparent"
    textColor: "{colors.foreground}"
    padding: "18px 0"
---

# Design System: Director Finance

## Overview

**Creative North Star: "Luma-inspired luminous operations console"**

The interface keeps the user's pinned Luma-inspired luminosity and premium star
reference in a dark, practical finance workspace. Ink-blue surfaces, violet-tinted
off-white type, restrained lilac controls, and one quiet halo behind the geometric
star mark carry the direction. Functional screens come first; full visual polish
and elaborate motion remain deferred. This is a record of the built interface,
not final visual approval.

The surface is Operate: organizers review event finances, evidence, decisions, and
work in progress. Borders and labeled records carry structure; status color always
has text alongside it. There is no star animation, fabricated progress animation,
or generated imagery in the current implementation.

**Key Characteristics:**
- Luminous lilac controls are restrained against ink-blue layers.
- Evidence, money, and authority stay readable in compact, divided records.
- Unknown information remains explicit, and status is not communicated by color alone.

## Colors

The palette pairs cool ink-blue surfaces and violet-tinted text with a single lilac
interaction accent; green, amber, and rose are reserved for semantic status.

### Primary
- **Quiet Lilac:** the main action and selected-control color; pair it with the
  dark accent ink for legible text.

### Neutral
- **Ink Blue:** the page canvas and deepest form surface.
- **Raised Ink:** a higher surface for grouped content and hover states.
- **Violet Off-White:** primary text; **Muted Lavender Gray** carries secondary
  labels and supporting details.
- **Blue-Violet Lines:** separate rows and strengthen field boundaries without
  replacing the surface hierarchy.

### Semantic
- **Soft Green**, **Warm Amber**, and **Muted Rose** communicate recorded success,
  caution, and error. Keep the matching status text visible beside each color.

## Typography

**Display Font:** DM Sans Variable (with sans-serif fallback)
**Body Font:** DM Sans Variable (with sans-serif fallback)
**Label Font:** DM Sans Variable (with sans-serif fallback)

**Character:** Compact, neutral sans-serif typography favors quick scanning over
editorial display. The bundled variable font provides consistent weights across
the dashboard and workbench.

### Hierarchy
- **Headline** (550, 30px, 1.25 line height): page titles.
- **Title** (600, 17px, 1.4 line height): section headings.
- **Body** (400, 14px, 1.55 line height): ordinary reading and table context.
- **Label** (550, 12px): field labels, compact actions, and controls.
- **Supporting copy** (11–12px, 1.7 line height where used): explanatory notes,
  status detail, and secondary record context.

## Layout

The event workspace uses a persistent navigation rail for Overview, Cases &
evidence, Approvals, Activity, Learning, Reports, and Connections. The main area
keeps the financial position as a labeled four-column register and presents work
records as divided rows, with approval actions and exact hashes kept together.
On small screens the rail becomes a toggleable drawer and the position register
becomes two columns.

On the dashboard, the Finney workbench and budget allocations appear after the
opening position/intake area and before obligations and the overview grids. The
workbench is a grouped task surface: people can ask Finney to work, add a reported
record, or upload a document. The budget surface follows with the current
allocation register and, when opened, an inline proposal form. The UI describes
requests and proposals as queued or pending; its appearance does not establish
that a provider accepted a request or completed an external action.

At the 680px breakpoint, the workbench narrows its panel padding, lets its mode
controls share available width, stacks labeled fields, and makes form actions
full width. Budget decision rows stack vertically and their action buttons share
the row. The budget register may scroll horizontally on narrow screens; long
category names wrap within table cells and decision rows instead of widening the
page. Desktop and mobile fixture captures were reviewed independently. One P2
long-name wrapping issue was fixed and confirmed resolved.

## Elevation & Depth

Depth comes mainly from tonal surface steps and thin borders. The single soft
lavender halo behind the star mark is atmospheric; a shadow is reserved for the
mobile navigation drawer when it opens. Loading feedback is limited to the actual
loading indicator, with short state transitions disabled under
`prefers-reduced-motion`.

## Shapes

Controls use gently rounded corners (8px), the workbench panel is slightly
rounder (12px), and the broader shell uses the 13px radius token. The file chooser
button has a tighter 5px corner. Dividers stay square and quiet; form fields keep
a clear stroke against the page surface.

## Components

These notes capture the rendered frontend patterns and the supplied desktop and
mobile fixture review. Provider acceptance and integration evidence remain in the
coordinator's separate project record.

### Buttons and workbench mode controls
- **Character:** restrained, clear actions inside an operational tool.
- The primary action uses lilac fill and dark ink; secondary actions are outlined
  against the dark surface. Keep the global visible focus outline.
- The three workbench modes—Ask Finney, Add a record, and Upload a document—are
  compact controls. The selected mode uses the accent fill and the same dark
  accent ink as the primary button; the other modes stay outlined.
- On mobile, mode buttons flex evenly while keeping their labels on one line.

### Workbench panel and form fields
- The panel sits on the raised surface with internal space around its heading,
  mode controls, and form. It is a functional grouping, not a modal.
- Labels stay above their fields. Text fields, selects, and textareas span their
  available width, use a darker inset surface, and keep a visible border.
- The prompt, manual record, and upload forms share this structure. Long helper
  text and error/status messages wrap within the panel; errors use `role="alert"`
  and successful queue notices use `role="status"`.
- At narrow widths, input text is at least 16px, fields stack, and submit actions
  fill the available width.

### Budget allocation register
- Use a semantic four-column table for Category, Allocated, Committed, and
  Remaining. Keep the table compact and use row dividers rather than nested cards.
- Money values remain aligned with their labels. Category text can wrap inside
  the cell; allow horizontal table scrolling when the viewport cannot fit the
  columns.
- When no categories exist, show a short explanation and a proposal action. Keep
  the note that allocations plan spending while recorded cash remains separate.

### Budget proposal form
- Open the proposal inline below the register, separated by a top rule and extra
  breathing room. The fields cover category, amount, and rationale; new
  categories also ask for a name.
- Keep the reason directly associated with the proposed amount. Supporting copy
  makes clear that a director decision is required before an allocation changes.
- On mobile, stack the fields and let the submit action use the full row width.

### Allocation decision rows
- Each decision is a divided row with category and amount, rationale, status,
  then any available actions. Keep approval and rejection actions beside the
  proposal on desktop; stack them with the row on mobile.
- Long category names and rationales wrap anywhere within the content column.
  This is a required layout behavior, confirmed by the desktop and mobile fixture
  review after the P2 wrap correction.
- Show pending status in text. The interface can show director decision controls
  only to the director, and waiting copy for other eligible viewers; visual
  affordances do not replace backend authorization.

### Sign-in
- Keep email and password labels visible, use a single primary action, and show
  authentication errors beside the form with recovery guidance. The same form
  switches to sign-up and shows confirmation pending when Supabase returns no
  session. A separate footer explains director-owned Gmail access.

## Do's and Don'ts

### Do:
- **Do** keep source context beside financial decisions and use explicit labels
  for unknown values.
- **Do** use the restrained lilac accent for primary actions and selected modes.
- **Do** retain visible field labels, keyboard focus, and text alongside semantic
  status colors.
- **Do** let long names wrap inside budget cells and decision rows at desktop and
  mobile widths.
- **Do** stack the workbench fields and decision actions at the mobile breakpoint.

### Don't:
- **Don't** use color alone to communicate approval, error, or success.
- **Don't** animate the star mark or invent progress motion.
- **Don't** let a long category name force the register or decision row wider than
  its available content area.
- **Don't** present a queued request or pending proposal as provider acceptance,
  completed work, cash, or a confirmed payment.

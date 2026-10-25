import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import test from "node:test";
import {
  CaseWorkspace,
  caseSourceIds,
  sourceDisplayTitle,
  caseBlockerNotes,
} from "../src/components/case-workspace";
import { snapshotSchema } from "../src/lib/contracts";

const org = "11111111-1111-4111-8111-111111111111";
const run = "22222222-2222-4222-8222-222222222222";
const caseId = "33333333-3333-4333-8333-333333333333";
const sourceId = "44444444-4444-4444-8444-444444444444";
function snapshot() {
  return snapshotSchema.parse({
    organization: { id: org, name: "TEST ONLY event" },
    run: {
      id: run,
      name: "TEST ONLY run",
      status: "active",
      currency: "USD",
      revision: 1,
    },
    position: {
      currency: "USD",
      cash_minor: null,
      committed_minor: null,
      receivable_minor: null,
      available_minor: null,
      evidence_status: "unknown",
      reconciled_at: null,
    },
    cases: [
      {
        id: caseId,
        title: "TEST ONLY revised invoice",
        status: "needs_review",
        version: 2,
        updated_at: "2026-10-25T00:00:00Z",
        data: {
          source_ids: [sourceId],
          finding: {
            decision: "investigate",
            explanation: "TEST ONLY: the revised amount needs review.",
            proposed_action: {
              action: "investigate",
              amount_minor: "7500",
              currency: "USD",
            },
            blocking_requirements: [
              { stage: "execution", requirement: "human_approval" },
            ],
          },
        },
      },
    ],
    approvals: [],
    activity: [],
    improvements: {
      skill_versions: [],
      eval_runs: [],
      eval_results: [],
      promotions: [],
    },
    connections: [],
    source_items: [
      {
        id: sourceId,
        source_type: "upload",
        version: 1,
        metadata: { filename: "original.txt" },
      },
      {
        id: "55555555-5555-4555-8555-555555555555",
        source_type: "upload",
        metadata: { filename: "unrelated-private.txt" },
      },
    ],
    reports: [],
    worker: { status: "online", last_seen_at: null },
    updated_at: "2026-10-25T00:00:00Z",
  });
}

test("case source selection uses canonical source_ids and deduplicates them", () => {
  assert.deepEqual(caseSourceIds({ source_ids: [sourceId, sourceId] }), [
    sourceId,
  ]);
  assert.deepEqual(
    caseSourceIds({ source_refs: [{ id: sourceId, version: 2 }] }),
    [sourceId],
  );
  assert.deepEqual(caseSourceIds({ source_ids: "invalid" }), []);
});

test("case workspace shows only linked documents and a proposed amount, never inferred settlement", () => {
  const state = snapshot();
  const html = renderToStaticMarkup(
    createElement(CaseWorkspace, {
      item: state.cases[0],
      snapshot: state,
      onBack: () => {},
      onReview: () => {},
      busy: false,
      canWork: true,
      decisions: null,
      evidenceForm: null,
    }),
  );
  assert.match(html, /original.txt/);
  assert.doesNotMatch(html, /unrelated-private/);
  assert.match(html, /Proposed amount/);
  assert.match(html, /\$75\.00/);
  assert.match(html, /human approval/);
  assert.doesNotMatch(html, /Invoice settled|Payment confirmed|>Paid</);
});

test("a case without a prepared amount does not invent money or completed work", () => {
  const state = snapshot();
  state.cases[0].data.finding = {};
  const html = renderToStaticMarkup(
    createElement(CaseWorkspace, {
      item: state.cases[0],
      snapshot: state,
      onBack: () => {},
      onReview: () => {},
      busy: false,
      canWork: false,
      decisions: null,
      evidenceForm: null,
    }),
  );
  assert.match(html, /Ready when you are/);
  assert.doesNotMatch(html, /\$0\.00|Proposed amount|Payment confirmed/);
  assert.match(html, /disabled=""[^>]*>Check invoice/);
});

test("a later stored reply precedes the earlier review without changing its amount or hiding decisions", () => {
  const state = snapshot();
  state.cases[0].version = 13;
  const finding = state.cases[0].data.finding as Record<string, unknown>;
  finding.provenance = { source_case_version: 8 };
  finding.explanation =
    "TEST ONLY earlier update failed; manual fix requested.";
  state.cases[0].data.director_responses = [
    {
      message: "TEST ONLY earlier conversation",
      provenance: { source_case_version: 10 },
    },
    {
      message:
        "TEST ONLY latest: revised 420 obligation recorded; budget rejected; cash unknown.",
      provenance: { source_case_version: 12 },
    },
  ];
  const html = renderToStaticMarkup(
    createElement(CaseWorkspace, {
      item: state.cases[0],
      snapshot: state,
      onBack: () => {},
      onReview: () => {},
      busy: false,
      canWork: true,
      decisions: createElement(
        "button",
        null,
        "TEST ONLY exact approval control",
      ),
      evidenceForm: null,
    }),
  );
  assert.match(html, /TEST ONLY latest:/);
  assert.match(html, /TEST ONLY exact approval control/);
  assert.match(html, /TEST ONLY earlier conversation/);
  assert.doesNotMatch(
    html,
    /TEST ONLY earlier update failed|Earlier proposed amount|Based on case|Stored agent response|Source provenance|Decision record|\$75\.00|\$420\.00|Payment confirmed|>Paid</,
  );
});

test("a response from an older case version does not demote a newer prepared review", () => {
  const state = snapshot();
  (state.cases[0].data.finding as Record<string, unknown>).provenance = {
    source_case_version: 8,
  };
  state.cases[0].data.director_responses = [
    { message: "TEST ONLY old reply", provenance: { source_case_version: 7 } },
  ];
  const html = renderToStaticMarkup(
    createElement(CaseWorkspace, {
      item: state.cases[0],
      snapshot: state,
      onBack: () => {},
      onReview: () => {},
      busy: false,
      canWork: true,
      decisions: null,
      evidenceForm: null,
    }),
  );
  assert.match(html, /TEST ONLY: the revised amount needs review/);
  assert.doesNotMatch(
    html,
    /TEST ONLY old reply|Earlier prepared review|Finney’s latest reply/,
  );
});

test("privacy-projected source metadata uses the linked case name, not an internal external ID", () => {
  const state = snapshot();
  state.source_items[0] = {
    ...state.source_items[0],
    metadata: {},
    external_id: "guided_demo:finney-mid-event-v1:av",
    source_type: "guided_demo",
  };
  const html = renderToStaticMarkup(
    createElement(CaseWorkspace, {
      item: state.cases[0],
      snapshot: state,
      onBack: () => {},
      onReview: () => {},
      busy: false,
      canWork: true,
      decisions: null,
      evidenceForm: null,
    }),
  );
  assert.match(html, /<h2>Invoice<\/h2>/);
  assert.doesNotMatch(html, /Version|Source provenance|guided_demo/);
  const primary = html.split("Source provenance")[0];
  assert.doesNotMatch(primary, /guided_demo:finney-mid-event-v1:av/);
});

test("director requests and email sources never masquerade as the linked invoice", () => {
  assert.equal(
    sourceDisplayTitle(
      {
        source_type: "director_message",
        external_id: "director-message:fictional-job",
        metadata: {},
      },
      "Harbor AV · revised invoice",
    ),
    "Director request",
  );
  assert.equal(
    sourceDisplayTitle(
      { source_type: "gmail", metadata: {} },
      "Harbor AV · revised invoice",
    ),
    "Email",
  );
  assert.equal(
    sourceDisplayTitle(
      { source_type: "guided_demo", metadata: {} },
      "Harbor AV · revised invoice",
    ),
    "Invoice",
  );
});

test("director requests never appear as source tabs and current result keeps its budget action", () => {
  const state = snapshot();
  const request = "66666666-6666-4666-8666-666666666666";
  state.cases[0].data.source_ids = [request, sourceId];
  state.cases[0].data.director_request = "Please compare the invoices.";
  state.source_items.push({
    id: request,
    source_type: "director_message",
    metadata: { submitted_by: "DO-NOT-RENDER" },
  });
  const html = renderToStaticMarkup(
    createElement(CaseWorkspace, {
      item: state.cases[0],
      snapshot: state,
      onBack: () => {},
      onReview: () => {},
      onViewBudget: () => {},
      busy: false,
      canWork: true,
      decisions: null,
      evidenceForm: null,
    }),
  );
  assert.doesNotMatch(html, new RegExp(`data-source-id="${request}"`));
  assert.doesNotMatch(html, /DO-NOT-RENDER|submitted_by|Version 2|Updated/);
  assert.match(html, /Please compare the invoices/);
  assert.match(html, /data-tutorial="view-budget"/);
  assert.match(html, /See budget/);
});

test("blocker notes distinguish recording, payment and settlement without schema jargon", () => {
  assert.deepEqual(
    caseBlockerNotes([
      { stage: "obligation_recording", requirement: "payer_identity" },
      { stage: "approval_request", requirement: "recipient_destination" },
      { stage: "approval_request", requirement: "recipient_destination" },
      { stage: "execution", requirement: "human_approvals" },
      {
        stage: "settlement_claim",
        requirement: "independent_payment_verification",
      },
    ]),
    [
      {
        heading: "Needs your help",
        messages: ["Confirm who paid and whom the event owes."],
      },
      {
        heading: "Before payment",
        messages: [
          "Payment needs verified bank or wallet details.",
          "Get the required human approval before sending payment.",
        ],
      },
      {
        heading: "Before marking it paid",
        messages: [
          "Wait for independent confirmation before marking the payment as settled.",
        ],
      },
    ],
  );
});
test("an exact visible blocker note is not repeated, but hidden or differently worded caveats retain the note", () => {
  const blockers = [
    { stage: "approval_request", requirement: "recipient_destination" },
  ];
  const explanation =
    "The invoice is recorded. Payment needs verified bank or wallet details.";
  assert.deepEqual(caseBlockerNotes(blockers, explanation), []);
  const hidden =
    "The invoice is recorded.\n\n" +
    "Supporting details remain on file. ".repeat(40) +
    explanation;
  assert.deepEqual(caseBlockerNotes(blockers, hidden), [
    {
      heading: "Before payment",
      messages: ["Payment needs verified bank or wallet details."],
    },
  ]);
  assert.equal(
    caseBlockerNotes(
      blockers,
      "The payment destination was missing but is now verified.",
    ).length,
    1,
  );
  assert.equal(
    caseBlockerNotes(
      [{ stage: "obligation_recording", requirement: "recipient_destination" }],
      "Invoice recorded.",
    )[0].heading,
    "Needs your help",
  );
});
test("payment requirements do not imply the invoice still needs recording or block viewing budget", () => {
  const state = snapshot();
  (
    state.cases[0].data.finding as Record<string, unknown>
  ).blocking_requirements = [
    { stage: "approval_request", requirement: "recipient_destination" },
  ];
  const html = renderToStaticMarkup(
    createElement(CaseWorkspace, {
      item: state.cases[0],
      snapshot: state,
      onBack: () => {},
      onReview: () => {},
      onViewBudget: () => {},
      busy: false,
      canWork: true,
      decisions: null,
      evidenceForm: null,
    }),
  );
  assert.match(html, /Before payment/);
  assert.match(html, /Payment needs verified bank or wallet details/);
  assert.doesNotMatch(
    html,
    /Before we go ahead|recipient destination|approval request|recipient_destination|approval_request/,
  );
  assert.match(html, /data-tutorial="view-budget"/);
});

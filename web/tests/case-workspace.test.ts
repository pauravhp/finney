import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import test from "node:test";
import {
  CaseWorkspace,
  caseSourceIds,
  sourceDisplayTitle,
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
  assert.match(html, /Ready for review/);
  assert.doesNotMatch(html, /\$0\.00|Proposed amount|Payment confirmed/);
  assert.match(html, /disabled=""[^>]*>Request review/);
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
  assert.ok(
    html.indexOf("TEST ONLY latest:") <
      html.indexOf("TEST ONLY earlier update failed"),
  );
  assert.ok(
    html.indexOf("TEST ONLY exact approval control") <
      html.indexOf("Earlier prepared review"),
  );
  assert.match(html, /Earlier prepared review · based on case v8/);
  assert.match(html, /Based on case v12 · Stored agent response/);
  assert.match(html, /Earlier replies \(1\)/);
  assert.match(html, /TEST ONLY earlier conversation/);
  assert.match(html, /Earlier proposed amount/);
  assert.match(html, /\$75\.00/); // Retains the prepared action; never parses money from reply prose.
  assert.doesNotMatch(html, /\$420\.00|Payment confirmed|>Paid</);
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
  assert.ok(
    html.indexOf("TEST ONLY: the revised amount needs review.") <
      html.indexOf("TEST ONLY old reply"),
  );
  assert.doesNotMatch(html, /Earlier prepared review|Finney’s latest reply/);
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
  assert.match(html, /<h2>TEST ONLY revised invoice<\/h2>/);
  assert.match(html, /Practice document/);
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
    "Email · Harbor AV · revised invoice",
  );
  assert.equal(
    sourceDisplayTitle(
      { source_type: "guided_demo", metadata: {} },
      "Harbor AV · revised invoice",
    ),
    "Harbor AV · revised invoice",
  );
});

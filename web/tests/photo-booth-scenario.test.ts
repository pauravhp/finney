import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { snapshotSchema } from "../src/lib/contracts";
import {
  PHOTO_BOOTH_SCENARIO_ID,
  PHOTO_BOOTH_OPENING_PROMPT,
  photoBoothContext,
  caseReviewPayload,
  shouldSubmitScenarioPrompt,
} from "../src/lib/photo-booth-scenario";
import {
  FinneyCompanion,
  companionState,
} from "../src/components/finney-companion";
import { CaseWorkspace } from "../src/components/case-workspace";
const org = "11111111-1111-4111-8111-111111111111",
  run = "22222222-2222-4222-8222-222222222222",
  event = "33333333-3333-4333-8333-333333333333",
  vendor = "44444444-4444-4444-8444-444444444444",
  source = "55555555-5555-4555-8555-555555555555";
function snapshot() {
  return snapshotSchema.parse({
    organization: { id: org, name: "Finney test event" },
    run: {
      id: run,
      name: "Practice",
      currency: "USD",
      status: "active",
      revision: 1,
      scenario: {
        id: PHOTO_BOOTH_SCENARIO_ID,
        title: "HarborHacks",
        brief:
          "200 attendees. Five days to go. The team is considering a photo booth.",
        status: "ready",
        synthetic: true,
        steps: [
          {
            id: "review",
            title: "Can we afford the photo booth?",
            case_id: event,
            prompt: PHOTO_BOOTH_OPENING_PROMPT,
          },
        ],
      },
    },
    position: {
      currency: "USD",
      cash_minor: "620000",
      committed_minor: "550000",
      receivable_minor: null,
      available_minor: "70000",
      evidence_status: "synthetic_scenario",
      reconciled_at: null,
    },
    cases: [
      {
        id: vendor,
        title: "Juniper Kitchen · signed replacement JK-200-A",
        status: "needs_review",
        version: 1,
        data: { source_ids: [source] },
        updated_at: "2026-10-25T12:00:00Z",
      },
      {
        id: event,
        title: "HarborHacks · photo booth decision",
        status: "needs_review",
        version: 1,
        data: { source_ids: [source] },
        updated_at: "2026-10-25T11:00:00Z",
      },
    ],
    source_items: [
      {
        id: source,
        source_type: "guided_demo",
        version: 2,
        external_id: "guided_demo:finney-photo-booth-v1:catering",
        metadata: {},
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
    worker: { status: "online", last_seen_at: null },
    updated_at: "2026-10-25",
  });
}
test("new scenario selects its event-wide case and keeps the exact editable question", () => {
  const state = snapshot();
  assert.equal(photoBoothContext(state)?.caseId, event);
  assert.equal(photoBoothContext(state)?.prompt, PHOTO_BOOTH_OPENING_PROMPT);
  assert.equal(companionState(state).caseId, event);
  assert.equal(companionState(state).detail, "Can we afford the photo booth?");
  assert.deepEqual(caseReviewPayload(state, state.cases[1]), {
    case_id: event,
    expected_version: 1,
    message: PHOTO_BOOTH_OPENING_PROMPT,
  });
  assert.deepEqual(caseReviewPayload(state, state.cases[0]), {
    case_id: vendor,
    expected_version: 1,
  });
});
test("intro presents the situation without executing work or disclosing corrected outcomes", () => {
  const state = snapshot();
  let calls = 0;
  const html = renderToStaticMarkup(
    createElement(FinneyCompanion, {
      snapshot: state,
      onOpenCase: () => {
        calls++;
      },
      onAsk: () => {
        calls++;
        return true;
      },
    }),
  );
  assert.equal(calls, 0);
  assert.match(html, /HarborHacks/);
  assert.match(html, /200 attendees/);
  assert.match(html, /Start with a question/);
  assert.match(html, /Skip introduction/);
  assert.doesNotMatch(
    html,
    /Harbor AV|\$750|\$150|480\.00|420\.00|data-tutorial="review-case"/,
  );
  state.run.scenario!.status = "preparing";
  assert.equal(photoBoothContext(state)?.ready, false);
});
test("event documents have readable source-case names and explicit review keeps the approved scope", () => {
  const state = snapshot();
  state.source_items.push({
    id: "66666666-6666-4666-8666-666666666666",
    source_type: "guided_demo",
    external_id: "guided_demo:finney-photo-booth-v1:event",
    version: 1,
  });
  state.cases[1].data.source_ids = [
    source,
    "66666666-6666-4666-8666-666666666666",
  ];
  const html = renderToStaticMarkup(
    createElement(CaseWorkspace, {
      item: state.cases[1],
      snapshot: state,
      onBack: () => {},
      onReview: () => {},
      busy: false,
      canWork: true,
      decisions: null,
      evidenceForm: null,
    }),
  );
  assert.match(html, /Review event/);
  assert.match(html, /Juniper Kitchen/);
  assert.match(html, /Juniper Kitchen/);
  assert.doesNotMatch(html, /Check invoice|Harbor AV/);
});
test("Enter sends, Shift Enter adds a line, and IME composition never submits", () => {
  assert.equal(shouldSubmitScenarioPrompt("Enter", false, false), true);
  assert.equal(shouldSubmitScenarioPrompt("Enter", true, false), false);
  assert.equal(shouldSubmitScenarioPrompt("Enter", false, true), false);
  assert.equal(shouldSubmitScenarioPrompt("Enter", false, false, 229), false);
  assert.equal(shouldSubmitScenarioPrompt("a", false, false), false);
});

test("many event documents use one descriptive chooser and distinguish the earlier invoice", () => {
  const state = snapshot();
  const more = [
    "66666666-6666-4666-8666-666666666666",
    "77777777-7777-4777-8777-777777777777",
    "88888888-8888-4888-8888-888888888888",
    "99999999-9999-4999-8999-999999999999",
  ];
  state.source_items.push(
    ...more.map((id, index) => ({
      id,
      source_type: "guided_demo",
      version: 1,
      metadata: { filename: `Document ${index + 1}` },
    })),
  );
  state.cases[1].data.source_ids = more;
  state.cases[1].data.superseded_source_ids = [source];
  const html = renderToStaticMarkup(
    createElement(CaseWorkspace, {
      item: state.cases[1],
      snapshot: state,
      onBack: () => {},
      onReview: () => {},
      busy: false,
      canWork: true,
      decisions: null,
      evidenceForm: null,
    }),
  );
  assert.match(html, /aria-label="Document"/);
  assert.match(html, /Previous · Catering order/);
  assert.doesNotMatch(html, /aria-label="Case documents"/);
});

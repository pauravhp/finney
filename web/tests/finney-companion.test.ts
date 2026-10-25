import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  FinneyCompanion,
  companionState,
  caseWorkState,
  replyForCompanionCommand,
} from "../src/components/finney-companion";
import { snapshotSchema } from "../src/lib/contracts";
const org = "11111111-1111-4111-8111-111111111111",
  run = "22222222-2222-4222-8222-222222222222",
  id = "33333333-3333-4333-8333-333333333333";
function snapshot() {
  return snapshotSchema.parse({
    organization: { id: org, name: "Harbor" },
    run: {
      id: run,
      name: "Harbor",
      currency: "USD",
      status: "active",
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
        id,
        title: "Harbor AV · revised invoice",
        status: "needs_review",
        version: 7,
        updated_at: "2026-10-25T10:00:00Z",
        data: {},
      },
    ],
    approvals: [],
    activity: [],
    connections: [],
    improvements: {
      skill_versions: [],
      eval_runs: [],
      eval_results: [],
      promotions: [],
    },
    worker: { status: "online", last_seen_at: null },
    updated_at: "2026-10-25T10:00:00Z",
  });
}
test("companion uses actual per-case jobs; old failure cannot override a later completed request", () => {
  const state = snapshot();
  assert.equal(caseWorkState(state, id), "ready");
  state.jobs = [
    {
      case_id: id,
      command_type: "review_case",
      status: "queued",
      created_at: "2026-10-25T10:00:00Z",
    },
  ];
  assert.equal(caseWorkState(state, id), "queued");
  state.jobs[0].status = "running";
  assert.equal(caseWorkState(state, id), "running");
  state.jobs[0].status = "failed";
  assert.equal(caseWorkState(state, id), "failed");
  state.jobs.push({
    case_id: id,
    command_type: "review_case",
    status: "completed",
    created_at: "2026-10-25T11:00:00Z",
  });
  assert.equal(caseWorkState(state, id), "finishing");
  state.jobs[1].id = "completed-job";
  state.cases[0].data.finding = {
    explanation: "Checked the invoice.",
    provenance: { job_id: "completed-job" },
  };
  assert.equal(caseWorkState(state, id), "completed");
  assert.doesNotMatch(companionState(state).title, /Paid|settled|approved/i);
});
test("pending human budget decision takes priority over background work", () => {
  const state = snapshot();
  state.jobs = [
    { case_id: id, command_type: "review_case", status: "running" },
  ];
  state.budget.decisions = [
    {
      name: "AV",
      status: "pending",
      allocated_minor: "100000",
      currency: "USD",
    },
  ];
  assert.deepEqual(companionState(state), {
    kind: "attention",
    title: "Your call.",
    detail: "AV budget",
    action: "budget",
    actionLabel: "Review budget",
    amount: "100000",
    currency: "USD",
  });
});
test("foreign jobs do not fabricate work on the selected case", () => {
  const state = snapshot();
  state.jobs = [
    { case_id: "other-case", command_type: "review_case", status: "running" },
  ];
  assert.equal(caseWorkState(state, id), "ready");
});
test("immediate submission is visible without fake progress or audit chrome", () => {
  const html = renderToStaticMarkup(
    createElement(FinneyCompanion, {
      snapshot: snapshot(),
      busy: true,
      onOpenCase: () => {},
      onAsk: () => {},
    }),
  );
  assert.match(html, /On it\./);
  assert.match(html, /data-state="running"/);
  assert.match(html, /data-tutorial="open-alert"/);
  assert.match(html, /data-tutorial="ask-finney"/);
  assert.doesNotMatch(
    html,
    /Version|revision|Updated|provenance|25%|Paid|Confirmed/,
  );
});

test("personal replies require the exact completed command and matching case", () => {
  const state = snapshot();
  const command = {
    jobId: "my-question",
    type: "director_message",
    caseId: id,
  };
  state.cases[0].data.director_responses = [
    { job_id: "other-question", message: "An unrelated answer." },
    {
      job_id: "my-question",
      message: "Exact stored answer: USD 420.00 remains unpaid.",
    },
  ];
  state.jobs = [
    {
      id: "my-question",
      case_id: id,
      command_type: "director_message",
      status: "running",
    },
  ];
  assert.equal(replyForCompanionCommand(state, command), null);
  state.jobs[0].status = "completed";
  assert.equal(
    replyForCompanionCommand(state, command)?.message,
    "Exact stored answer: USD 420.00 remains unpaid.",
  );
  assert.equal(
    replyForCompanionCommand(state, { ...command, jobId: "other-question" }),
    null,
  );
  assert.equal(
    replyForCompanionCommand(state, { ...command, caseId: "foreign-case" }),
    null,
  );
});
test("outside the practice event the alert follows current work, not a hardcoded vendor", () => {
  const state = snapshot();
  state.cases[0].status = "open";
  state.cases[0].updated_at = "2026-10-20";
  state.cases.push({
    ...state.cases[0],
    id: "44444444-4444-4444-8444-444444444444",
    title: "Café invoice",
    status: "needs_review",
    updated_at: "2026-10-25",
  });
  assert.equal(companionState(state).caseId, state.cases[1].id);
  state.run.scenario = {
    id: "practice",
    title: "Harbor",
    brief: "Fixture",
    synthetic: true,
    steps: [{ id: "catch", title: "Invoice", case_id: id }],
  };
  assert.equal(companionState(state).caseId, id);
});

import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  BudgetWorkbench,
  Workbench,
  budgetProposalArguments,
  manualEntryPayload,
} from "../src/components/workbench";

const scope = {
  organization_id: "d19587c6-6535-4455-b4cd-ea4819845ec1",
  run_id: "d19587c6-6535-4455-b4cd-ea4819845ec2",
};
const onRefresh = async () => {};

test("manual evidence uses exact minor-unit strings and rejects invalid direction/precision", () => {
  assert.deepEqual(
    manualEntryPayload(
      " TEST ONLY invoice ",
      "90071992547409.93",
      "USD",
      "payable",
    ),
    {
      source: "manual",
      description: "TEST ONLY invoice",
      amount_minor: "9007199254740993",
      currency: "USD",
      direction: "payable",
    },
  );
  assert.throws(() => manualEntryPayload("Invoice", "1.001", "USD", "payable"));
  assert.throws(() => manualEntryPayload("Invoice", "NaN", "USD", "payable"));
  assert.throws(() => manualEntryPayload("Invoice", "1", "USD", "paid"));
  assert.throws(() => manualEntryPayload(" ", "1", "USD", "payable"));
});

test("budget changes carry the displayed category version and exact allocation", () => {
  assert.deepEqual(
    budgetProposalArguments({
      line: { id: "test-line", version: 7 },
      name: "ignored",
      amount: "123.45",
      currency: "USD",
      rationale: " TEST ONLY updated quote ",
      idempotencyKey: "test-request",
    }),
    {
      budget_line_id: "test-line",
      expected_version: 7,
      allocated_minor: "12345",
      rationale: "TEST ONLY updated quote",
      idempotency_key: "test-request",
    },
  );
  assert.deepEqual(
    budgetProposalArguments({
      name: " TEST ONLY food ",
      amount: "0",
      currency: "USD",
      rationale: "Cancel allocation",
      idempotencyKey: "test-request",
    }),
    {
      new_name: "TEST ONLY food",
      allocated_minor: "0",
      rationale: "Cancel allocation",
      idempotency_key: "test-request",
    },
  );
  assert.throws(() =>
    budgetProposalArguments({
      line: { id: "test-line" },
      name: "",
      amount: "1",
      currency: "USD",
      rationale: "Needs a version",
      idempotencyKey: "test-request",
    }),
  );
});

test("budget decisions remain explicit director controls and allocations stay distinct from cash", () => {
  const budget = {
    lines: [],
    decisions: [
      {
        id: "test-decision",
        name: "TEST ONLY food",
        currency: "USD",
        allocated_minor: "10000",
        rationale: "TEST ONLY quote",
        status: "pending",
      },
    ],
  };
  const viewer = renderToStaticMarkup(
    createElement(BudgetWorkbench, {
      scope,
      currency: "USD",
      budget,
      canEdit: false,
      canDecide: false,
      onRefresh,
    }),
  );
  assert.match(viewer, /Awaiting a director decision/);
  assert.doesNotMatch(viewer, />Approve allocation</);
  assert.match(
    viewer,
    /Allocations plan spending; recorded cash remains separate/,
  );
  const director = renderToStaticMarkup(
    createElement(BudgetWorkbench, {
      scope,
      currency: "USD",
      budget,
      canEdit: true,
      canDecide: true,
      onRefresh,
    }),
  );
  assert.match(director, />Approve allocation</);
  assert.match(director, />Reject allocation</);
});

test("readonly workbench labels the editor requirement and disables submissions", () => {
  const html = renderToStaticMarkup(
    createElement(Workbench, {
      scope,
      currency: "USD",
      cases: [],
      canEdit: false,
      busy: false,
      onRefresh,
      onCommand: async () => false,
    }),
  );
  assert.match(html, /An active director or finance team member/);
  assert.match(html, /id="finney-message"[^>]*disabled/);
  assert.match(html, /disabled=""[^>]*>Queue request/);
});

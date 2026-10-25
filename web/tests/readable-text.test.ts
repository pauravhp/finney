import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  ReadableText,
  sourceDocumentText,
} from "../src/components/readable-text";
import { Workbench } from "../src/components/workbench";

test("bundle descriptions never hide underlying contracts or payment timing evidence", () => {
  const output = sourceDocumentText({
    description: "Sponsor packet",
    documents: [
      { title: "Agreement", text: "USD 2,500 pledged." },
      {
        title: "Later message",
        body: "Payment has NOT been sent. No receipt attached.",
      },
    ],
  });
  assert.match(output, /Sponsor packet/);
  assert.match(output, /USD 2,500 pledged/);
  assert.match(output, /Payment has NOT been sent/);
});
test("model Markdown preserves amounts, qualifications and escapes active content", () => {
  const output = renderToStaticMarkup(
    createElement(ReadableText, {
      text: "**Amount:** $420.00\n\n- Not paid.\n- Approval was denied.\n\n<script>alert(1)</script>",
    }),
  );
  assert.match(output, /<strong>Amount:<\/strong>/);
  assert.match(output, /\$420\.00/);
  assert.match(output, /Not paid/);
  assert.match(output, /Approval was denied/);
  assert.doesNotMatch(output, /<script>/);
});
test("case uploads keep scope binding without redundant task tabs or case selector", () => {
  const output = renderToStaticMarkup(
    createElement(Workbench, {
      scope: {
        organization_id: "11111111-1111-4111-8111-111111111111",
        run_id: "22222222-2222-4222-8222-222222222222",
      },
      currency: "USD",
      cases: [],
      initialCaseId: "33333333-3333-4333-8333-333333333333",
      initialMode: "upload",
      contextual: true,
      canEdit: true,
      busy: false,
      onCommand: async () => true,
      onRefresh: async () => {},
    }),
  );
  assert.doesNotMatch(
    output,
    /Related case|Work with Finney|Choose a finance task/,
  );
  assert.match(output, /This document is/);
  assert.match(output, /Choose a document/);
});

test("long financial paragraphs lose no amounts, identifiers, caveats or words", () => {
  const text =
    "Sponsor pledged USD 2,500.00. Harbor AV is owed USD 420.00; no payment was sent. Case 33333333-3333-4333-8333-333333333333 v12 supersedes v8. " +
    "A declined allocation never erases the liability. ".repeat(15);
  const html = renderToStaticMarkup(createElement(ReadableText, { text }));
  const visible = html.replace(/<[^>]*>/g, "");
  assert.equal(visible, text.trim());
  assert.match(visible, /USD 2,500\.00/);
  assert.match(visible, /USD 420\.00/);
  assert.match(
    visible,
    /33333333-3333-4333-8333-333333333333 v12 supersedes v8/,
  );
});

test("guided budget decisions ignore unrelated categories and amounts", async () => {
  const { guidedAVDecision } = await import("../src/components/guided-demo");
  const { snapshotSchema } = await import("../src/lib/contracts");
  const state = snapshotSchema.parse({
    organization: {
      id: "11111111-1111-4111-8111-111111111111",
      name: "Fixture",
    },
    run: {
      id: "22222222-2222-4222-8222-222222222222",
      name: "Fixture",
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
    cases: [],
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
  state.budget = {
    lines: [{ id: "av-line", name: "AV" }],
    decisions: [
      { name: "Food", allocated_minor: "100000", status: "rejected" },
      { name: "AV", allocated_minor: "50000", status: "rejected" },
    ],
  };
  assert.equal(guidedAVDecision(state), undefined);
  state.budget.decisions.push({
    budget_line_id: "av-line",
    allocated_minor: "100000",
    currency: "USD",
    status: "approved",
  });
  assert.equal(guidedAVDecision(state)?.status, "approved");
});

test("actual guided packets retain every evidence body without internal scaffold labels", async () => {
  const { guidedSources } = await import("./fixtures/guided-source");
  for (const packet of [...guidedSources._INITIAL, guidedSources._REVISED]) {
    const output = sourceDocumentText(packet);
    for (const document of packet.documents as { text: string }[])
      assert.ok(output.includes(document.text));
    assert.ok(output.includes(String(packet.description)));
    assert.doesNotMatch(output, /External id:|Kind:|Headers:|Provider:|###/);
    assert.equal(output.split(String(packet.description)).length - 1, 1);
  }
  const mail = sourceDocumentText({
    description: "Invoice",
    headers: {
      from: "billing@example.invalid",
      to: "director@example.invalid",
      subject: "Corrected total",
      date: "2026-10-25",
    },
    documents: [{ kind: "invoice", text: "USD 420.00 remains unpaid." }],
  });
  assert.match(mail, /From: billing@example.invalid/);
  assert.match(mail, /To: director@example.invalid/);
  assert.match(mail, /Subject: Corrected total/);
  assert.match(mail, /Date: 2026-10-25/);
  assert.match(mail, /USD 420\.00 remains unpaid/);
});

test("actual reply shape formats adjacent headings, tables, lists and italic without HTML injection", async () => {
  const { readFileSync } = await import("node:fs");
  const { message } = JSON.parse(
    readFileSync("tests/fixtures/catch-response.json", "utf8"),
  );
  const html = renderToStaticMarkup(
    createElement(ReadableText, { text: message }),
  );
  assert.match(html, /<h3>What changed<\/h3><div class="table-scroll"><table>/);
  assert.match(html, /<h3>Duplicate check<\/h3><ul>/);
  assert.match(html, /<h3>Record updated<\/h3><ul>/);
  assert.match(html, /<h3>Next decision<\/h3><p>/);
  assert.match(html, /<em>reported<\/em>/);
  assert.equal((html.match(/<tbody>/g) ?? []).length, 1);
  assert.equal((html.match(/<li>/g) ?? []).length, 9);
  for (const amount of [
    "420.00",
    "480.00",
    "60.00",
    "800.00",
    "380.00",
    "3,700.00",
    "7,800.00",
  ])
    assert.ok(html.includes(amount));
  assert.match(html, /not the whole mailbox/);
  assert.match(html, /rather than a tool result/);
  assert.doesNotMatch(html, /##|\|---/);
  const malicious = renderToStaticMarkup(
    createElement(ReadableText, {
      text: "## Review\n- *Unpaid* <script>alert(1)</script>\n| Amount | State |\n|---|---|\n| USD 420.00 | **Not paid** |",
    }),
  );
  assert.match(malicious, /&lt;script&gt;/);
  assert.doesNotMatch(malicious, /<script>/);
  assert.match(malicious, /<table>/);
});

import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  DirectorResponses,
  currentReplyParts,
} from "../src/components/director-responses";

test("actual replies preserve text and escape markup without exposing audit metadata", () => {
  const html = renderToStaticMarkup(
    createElement(DirectorResponses, {
      responses: [
        {
          id: "TEST-ONLY-reply",
          message:
            "First line\n<script>alert('fixture')</script>\nNo payment was sent.",
          consulted_source_ids: ["TEST-ONLY-source"],
          job_id: "TEST-ONLY-job",
          actor_trace_id: "TEST-ONLY-trace",
          provenance: {
            model: "TEST-ONLY-model",
            secret: "TEST-ONLY-private-secret",
          },
        },
      ],
    }),
  );
  assert.match(html, /Finney’s replies/);
  assert.match(html, /First line\n&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>|TEST-ONLY-private-secret/);
  for (const text of [
    "Sources consulted",
    "TEST-ONLY-source",
    "TEST-ONLY-job",
    "TEST-ONLY-trace",
    "Inspect reply provenance",
  ])
    assert.ok(!html.includes(text));
  assert.doesNotMatch(html, /Approve|execute_payment|Payment execution/);
});

test("consultation metadata stays out of the conversation surface", () => {
  const empty = renderToStaticMarkup(
    createElement(DirectorResponses, {
      responses: [{ message: "TEST ONLY reply", consulted_source_ids: [] }],
    }),
  );
  assert.doesNotMatch(empty, /No source documents were opened/);
  const missing = renderToStaticMarkup(
    createElement(DirectorResponses, {
      responses: [{ message: "TEST ONLY reply" }],
    }),
  );
  assert.doesNotMatch(missing, /Source consultation was not recorded/);
  assert.equal(
    renderToStaticMarkup(
      createElement(DirectorResponses, {
        responses: [null, { message: {} }, { message: " " }],
      }),
    ),
    "",
  );
});

test("long current replies disclose the unchanged remainder and retain all financial caveats", () => {
  const lead = "We owe USD 420.00, not USD 480.00. No payment has been made.";
  const rest =
    "\n\n## Evidence\n" +
    "The allocation was declined; the liability remains USD 420.00. ".repeat(
      20,
    ) +
    "\n\n## Limits\nNo approval or settlement. Cash remains unreconciled.";
  const message = lead + rest;
  assert.deepEqual(currentReplyParts(message, true), { lead, rest });
  assert.equal(currentReplyParts(message, false), null);
  assert.equal(currentReplyParts("Short answer.\n\nStill unpaid.", true), null);
  assert.equal(
    currentReplyParts("Long single paragraph. ".repeat(60), true),
    null,
  );
  const html = renderToStaticMarkup(
    createElement(DirectorResponses, {
      responses: [
        {
          message,
          consulted_source_ids: ["fictional-source"],
          job_id: "fictional-job",
        },
      ],
      collapseLong: true,
    }),
  );
  assert.ok(html.indexOf(lead) < html.indexOf("Read full response"));
  assert.match(html, /<details class="record-details reply-full-response">/);
  assert.doesNotMatch(html, /<details[^>]*open/);
  assert.match(html, /No approval or settlement/);
  assert.match(html, /Cash remains unreconciled/);
  assert.doesNotMatch(html, /fictional-source/);
  assert.doesNotMatch(html, /fictional-job/);
  assert.equal((html.match(/liability remains USD 420\.00/g) ?? []).length, 20);
});

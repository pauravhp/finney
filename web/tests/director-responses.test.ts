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

test("only an explicit Details marker discloses supplementary explanation", () => {
  const lead =
    "We owe USD 420.00. No payment has been made, and cash remains unreconciled.";
  const rest =
    "The vendor credited USD 60.00 against the original USD 480.00 invoice.";
  const message = lead + "\n\nDetails:\n" + rest;
  assert.deepEqual(currentReplyParts(message, true), { lead, rest });
  assert.deepEqual(currentReplyParts(message, false), { lead, rest });
  const html = renderToStaticMarkup(
    createElement(DirectorResponses, {
      responses: [{ message, job_id: "private-job" }],
    }),
  );
  assert.match(html, /director-response-primary/);
  assert.match(html, /director-response-details/);
  assert.match(html, /<summary>Details<\/summary>/);
  assert.doesNotMatch(html, /<details[^>]*open/);
  assert.ok(html.indexOf(lead) < html.indexOf("<summary>Details"));
  assert.ok(html.includes(rest));
  assert.doesNotMatch(html, /private-job/);
  assert.equal(lead + "\n\nDetails:\n" + rest, message);
});

test("long unmarked legacy replies remain whole, including late financial caveats", () => {
  const message =
    "The invoice was reviewed.\n\n" +
    "Additional source evidence remains on file. ".repeat(40) +
    "\n\nNo approval or settlement. Cash remains unreconciled.";
  assert.equal(currentReplyParts(message, true), null);
  const html = renderToStaticMarkup(
    createElement(DirectorResponses, {
      responses: [{ message }],
      collapseLong: true,
    }),
  );
  assert.doesNotMatch(html, /reply-full-response|<summary>/);
  assert.match(html, /No approval or settlement/);
  assert.match(html, /Cash remains unreconciled/);
  assert.equal(
    (html.match(/Additional source evidence remains on file/g) ?? []).length,
    40,
  );
  for (const malformed of [
    "Lead.\nDetails:\nBody.",
    "Lead.\n\nDetails: Body.",
    "\n\nDetails:\nBody.",
    "Lead.\n\nDetails:\n",
  ])
    assert.equal(currentReplyParts(malformed), null);
});

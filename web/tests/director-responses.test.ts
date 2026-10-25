import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { DirectorResponses } from "../src/components/director-responses";

test("actual replies preserve text, escape markup and show consulted-source/provenance linkage", () => {
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
    assert.ok(html.includes(text));
  assert.doesNotMatch(html, /Approve|execute_payment|Payment execution/);
});

test("unknown or empty consultation metadata is explicit without inventing sources", () => {
  const empty = renderToStaticMarkup(
    createElement(DirectorResponses, {
      responses: [{ message: "TEST ONLY reply", consulted_source_ids: [] }],
    }),
  );
  assert.match(empty, /No source documents were opened/);
  const missing = renderToStaticMarkup(
    createElement(DirectorResponses, {
      responses: [{ message: "TEST ONLY reply" }],
    }),
  );
  assert.match(missing, /Source consultation was not recorded/);
  assert.equal(
    renderToStaticMarkup(
      createElement(DirectorResponses, {
        responses: [null, { message: {} }, { message: " " }],
      }),
    ),
    "",
  );
});

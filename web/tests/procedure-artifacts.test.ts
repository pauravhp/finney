import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Procedure } from "../src/components/procedure";
import {
  MAX_PROCEDURE_BYTES,
  assertProcedureLineage,
  readProcedureArtifact,
  storedProcedureTexts,
} from "../src/lib/procedure-artifacts";

const scope = {
  organization_id: "d19587c6-6535-4455-b4cd-ea4819845ec1",
  run_id: "d19587c6-6535-4455-b4cd-ea4819845ec2",
};
const text =
  "# Skill\r\n\r\n## Investigation procedure\r\n\r\nRead current source versions.\r\n\r\n## Authority boundary\r\nNever pay.\r\n";
const hash = (value: string) =>
  createHash("sha256").update(value).digest("hex");
const parent = {
  id: "parent",
  skill_name: "organizer-expenses",
  content_sha256: hash(text),
  artifact_path: `${scope.organization_id}/${scope.run_id}/artifacts/${hash(text)}/parent.md`,
};
const row = { ...parent, id: "candidate", parent_version_id: "parent" };

test("actual stored bytes determine integrity before line-ending normalization", async () => {
  const value = await readProcedureArtifact(
    row,
    scope,
    async () => ({ data: new Blob([text]), error: null }),
    "candidate",
  );
  assert.equal(value, text);
  assert.equal(
    storedProcedureTexts(value).candidate,
    "Read current source versions.",
  );
  await assert.rejects(
    readProcedureArtifact(
      row,
      scope,
      async () => ({
        data: new Blob([text.replaceAll("\r\n", "\n")]),
        error: null,
      }),
      "candidate",
    ),
    /checksum/,
  );
});

test("foreign, traversing, and unrelated parent versions are refused before storage", () => {
  for (const path of [
    `foreign/${scope.run_id}/artifacts/hash/parent.md`,
    `${scope.organization_id}/${scope.run_id}/artifacts/../parent.md`,
    `${scope.organization_id}/${scope.run_id}/artifacts/%252e%252e/parent.md`,
  ])
    assert.throws(
      () =>
        assertProcedureLineage(row, { ...parent, artifact_path: path }, scope),
      /does not belong/,
    );
  assert.throws(
    () => assertProcedureLineage(row, { ...parent, id: "unrelated" }, scope),
    /recorded parent/,
  );
  assert.throws(
    () => assertProcedureLineage(row, { ...parent, run_id: "foreign" }, scope),
    /does not belong/,
  );
});

test("denied access, oversized objects and missing hashes fail without an invented comparison", async () => {
  await assert.rejects(
    readProcedureArtifact(
      row,
      scope,
      async () => ({
        data: null,
        error: { message: "private provider detail" },
      }),
      "baseline",
    ),
    /baseline procedure is unavailable/,
  );
  await assert.rejects(
    readProcedureArtifact(
      row,
      scope,
      async () => ({
        data: new Blob(["x".repeat(MAX_PROCEDURE_BYTES + 1)]),
        error: null,
      }),
      "candidate",
    ),
    /too large/,
  );
  let fetched = false;
  await assert.rejects(
    readProcedureArtifact(
      { ...row, content_sha256: "" },
      scope,
      async () => {
        fetched = true;
        return { data: new Blob(), error: null };
      },
      "candidate",
    ),
    /checksum/,
  );
  assert.equal(fetched, false);
});

test("full stored artifacts remain comparable when either section cannot be extracted", () => {
  const other = "A legacy complete skill without section headings.";
  assert.deepEqual(storedProcedureTexts(text, other), {
    candidate: text,
    baseline: other,
  });
  const changedAuthority = text.replace(
    "Never pay.",
    "Changed protected authority.",
  );
  assert.deepEqual(storedProcedureTexts(changedAuthority, text), {
    candidate: changedAuthority,
    baseline: text,
  });
});

test("generation metadata remains explicitly labeled and missing parent never invents a diff", () => {
  const html = renderToStaticMarkup(
    createElement(Procedure, {
      row: {
        ...row,
        metadata: {
          generation: {
            output: { procedure: "Recorded generation proposal." },
          },
        },
      },
      scope,
    }),
  );
  assert.match(html, /Showing recorded generation text/);
  assert.match(html, /Recorded generation proposal/);
  assert.match(html, /baseline version is unavailable/);
  assert.doesNotMatch(html, /Inspect procedure diff/);
  const unlinked = renderToStaticMarkup(
    createElement(Procedure, {
      row: { ...row, status: "candidate", parent_version_id: null },
      scope,
    }),
  );
  assert.match(unlinked, /No baseline is linked to this version/);
  assert.doesNotMatch(unlinked, /Inspect procedure diff/);
});

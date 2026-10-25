"use client";

import { createPatch } from "diff";
import { useEffect, useRef, useState } from "react";
import { textValue, type Scope } from "@/lib/contracts";
import { browserSupabase } from "@/lib/supabase/browser";
import {
  assertProcedureLineage,
  readProcedureArtifact,
  storedProcedureTexts,
  type ProcedureVersion,
} from "@/lib/procedure-artifacts";

function generation(row: ProcedureVersion) {
  const metadata = row.metadata as
    { generation?: { output?: Record<string, unknown> } } | undefined;
  return metadata?.generation?.output ?? {};
}

export function Procedure({
  row,
  baseline,
  scope,
}: {
  row: ProcedureVersion;
  baseline?: ProcedureVersion;
  scope: Scope;
}) {
  const identity = JSON.stringify([
    scope,
    row.id,
    row.artifact_path,
    row.content_sha256,
    row.parent_version_id,
    row.organization_id,
    row.run_id,
    row.skill_name,
    baseline?.id,
    baseline?.artifact_path,
    baseline?.content_sha256,
    baseline?.organization_id,
    baseline?.run_id,
    baseline?.skill_name,
  ]);
  const request = useRef(0);
  const [inspection, setInspection] = useState<{
    identity: string;
    raw: string;
    candidate: string;
    baseline?: string;
  } | null>(null);
  const [failure, setFailure] = useState<{
    identity: string;
    message: string;
  } | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  useEffect(
    () => () => {
      request.current++;
    },
    [identity],
  );
  const stored = inspection?.identity === identity ? inspection : null;
  const error = failure?.identity === identity ? failure.message : null;
  const fetching = loading === identity;
  const candidate =
    stored?.candidate ?? textValue(generation(row).procedure, "");
  const prior =
    stored?.baseline ??
    (baseline ? textValue(generation(baseline).procedure, "") : "");

  async function inspectArtifact() {
    const current = ++request.current;
    setLoading(identity);
    setFailure(null);
    setInspection(null);
    try {
      assertProcedureLineage(row, baseline, scope);
      const download = (path: string) =>
        browserSupabase().storage.from("finance-artifacts").download(path);
      const [raw, previous] = await Promise.all([
        readProcedureArtifact(row, scope, download, "candidate"),
        baseline
          ? readProcedureArtifact(baseline, scope, download, "baseline")
          : undefined,
      ]);
      if (current === request.current)
        setInspection({
          identity,
          raw,
          ...storedProcedureTexts(raw, previous),
        });
    } catch (cause) {
      if (current === request.current)
        setFailure({
          identity,
          message:
            cause instanceof Error
              ? cause.message
              : "The procedures could not be read. Retry inspection.",
        });
    } finally {
      if (current === request.current) setLoading(null);
    }
  }

  return (
    <div aria-busy={fetching}>
      {Boolean(generation(row).rationale) && (
        <p>{textValue(generation(row).rationale)}</p>
      )}
      {stored && (
        <p className="muted" role="status">
          Showing verified stored procedure text.
        </p>
      )}
      {!stored && (candidate || prior) && (
        <p className="muted">
          Showing recorded generation text. Inspect the stored versions to
          verify the comparison.
        </p>
      )}
      {candidate && prior ? (
        <details className="record-details" open={stored ? true : undefined}>
          <summary>Inspect procedure diff</summary>
          <pre>
            {createPatch(
              textValue(row.skill_name, "procedure"),
              prior,
              candidate,
              "baseline",
              "candidate",
            )}
          </pre>
          <div className="procedure-comparison">
            <div>
              <h4>Baseline</h4>
              <pre>{prior}</pre>
            </div>
            <div>
              <h4>Candidate</h4>
              <pre>{candidate}</pre>
            </div>
          </div>
        </details>
      ) : candidate ? (
        <details className="record-details" open={stored ? true : undefined}>
          <summary>Inspect candidate procedure</summary>
          <pre>{candidate}</pre>
        </details>
      ) : (
        <p className="muted">
          Procedure text must be read from the stored artifact.
        </p>
      )}
      {!baseline && Boolean(row.parent_version_id) && (
        <p className="muted">
          The baseline version is unavailable in this run. You can inspect the
          stored candidate.
        </p>
      )}
      {!baseline &&
        !row.parent_version_id &&
        row.status !== "baseline" &&
        row.status !== "baseline_reference" && (
          <p className="muted">
            No baseline is linked to this version. You can inspect the stored
            candidate.
          </p>
        )}
      {Boolean(row.artifact_path) && (
        <button onClick={inspectArtifact} disabled={fetching}>
          {fetching
            ? "Reading procedures…"
            : baseline
              ? "Compare stored procedures"
              : "Inspect private procedure artifact"}
        </button>
      )}
      {error && <p role="alert">{error}</p>}
      {stored && <pre className="diff">{stored.raw}</pre>}
    </div>
  );
}

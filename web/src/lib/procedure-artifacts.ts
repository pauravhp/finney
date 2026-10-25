import type { Scope } from "@/lib/contracts";

export type ProcedureVersion = Record<string, unknown>;
export const MAX_PROCEDURE_BYTES = 1_048_576;
type Download = (
  path: string,
) => Promise<{ data: Blob | null; error: unknown }>;

export function procedureArtifactPath(
  version: ProcedureVersion,
  scope: Scope,
  label: string,
) {
  const path = version.artifact_path;
  if (
    (version.organization_id !== undefined &&
      version.organization_id !== scope.organization_id) ||
    (version.run_id !== undefined && version.run_id !== scope.run_id) ||
    typeof path !== "string" ||
    !path.startsWith(`${scope.organization_id}/${scope.run_id}/artifacts/`) ||
    path.includes("\\") ||
    /%(?:2e|2f|5c|25)/i.test(path) ||
    path.split("/").some((part) => !part || part === "." || part === "..")
  )
    throw new Error(`The ${label} artifact path does not belong to this run.`);
  if (
    typeof version.content_sha256 !== "string" ||
    !/^[a-f0-9]{64}$/.test(version.content_sha256)
  )
    throw new Error(
      `The ${label} version has no valid content checksum. Stored comparison is unavailable.`,
    );
  return path;
}

export function assertProcedureLineage(
  row: ProcedureVersion,
  baseline: ProcedureVersion | undefined,
  scope: Scope,
) {
  procedureArtifactPath(row, scope, "candidate");
  if (!baseline) return;
  if (
    !baseline.id ||
    row.parent_version_id !== baseline.id ||
    (row.skill_name !== undefined && baseline.skill_name !== row.skill_name)
  )
    throw new Error(
      "The baseline is not the recorded parent of this procedure version.",
    );
  procedureArtifactPath(baseline, scope, "baseline");
}

export async function readProcedureArtifact(
  version: ProcedureVersion,
  scope: Scope,
  download: Download,
  label: string,
) {
  const path = procedureArtifactPath(version, scope, label);
  let result;
  try {
    result = await download(path);
  } catch {
    throw new Error(
      `The ${label} procedure could not be read. Check your connection and retry.`,
    );
  }
  if (result.error || !result.data)
    throw new Error(
      `The ${label} procedure is unavailable to this account. Check access and retry.`,
    );
  if (result.data.size > MAX_PROCEDURE_BYTES)
    throw new Error(
      `The ${label} artifact is too large to inspect inline. Use the authorized export tool.`,
    );
  const bytes = await result.data.arrayBuffer();
  if (bytes.byteLength > MAX_PROCEDURE_BYTES)
    throw new Error(
      `The ${label} artifact is too large to inspect inline. Use the authorized export tool.`,
    );
  const digest = Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
  if (digest !== version.content_sha256)
    throw new Error(
      `The ${label} artifact does not match its stored checksum. The comparison was not displayed.`,
    );
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new Error(
      `The ${label} artifact is not readable UTF-8 text. Use the authorized export tool.`,
    );
  }
}

export function investigationProcedure(content: string): string | null {
  const normalized = content.replaceAll("\r\n", "\n");
  const start = "## Investigation procedure\n",
    end = "## Authority boundary\n";
  if (
    normalized.split(start).length !== 2 ||
    normalized.split(end).length !== 2
  )
    return null;
  const remainder = normalized.split(start)[1];
  if (!remainder.includes(end)) return null;
  return remainder.split(end)[0].trim() || null;
}

export function storedProcedureTexts(candidate: string, baseline?: string) {
  const candidateSection = investigationProcedure(candidate);
  const baselineSection =
    baseline === undefined ? null : investigationProcedure(baseline);
  function protectedContext(content: string) {
    const normalized = content.replaceAll("\r\n", "\n");
    const start = "## Investigation procedure\n",
      end = "## Authority boundary\n";
    return JSON.stringify([
      normalized.slice(0, normalized.indexOf(start) + start.length),
      normalized.slice(normalized.indexOf(end)),
    ]);
  }
  // Compare matching representations; never mix a whole artifact with metadata or a section.
  if (
    candidateSection &&
    (baseline === undefined ||
      (baselineSection &&
        protectedContext(candidate) === protectedContext(baseline)))
  )
    return {
      candidate: candidateSection,
      baseline: baselineSection ?? undefined,
    };
  return { candidate, baseline };
}

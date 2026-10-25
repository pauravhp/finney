"use client";

import { useEffect, useState, type ReactNode } from "react";
import { ArrowLeft, FileText, LoaderCircle } from "lucide-react";
import { browserSupabase } from "@/lib/supabase/browser";
import {
  dateTime,
  displayRecord,
  formatMoney,
  textValue,
  type FinanceSnapshot,
} from "@/lib/contracts";
import {
  ReadableText,
  friendlyTitle,
  sourceDocumentText,
} from "@/components/readable-text";
import { DirectorResponses } from "@/components/director-responses";

type Row = Record<string, unknown>;
function record(value: unknown): Row {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Row)
    : {};
}
export function caseSourceIds(data: Row): string[] {
  const current =
    data.source_ids ?? data.source_refs ?? data.sources ?? data.evidence;
  const values = [
    ...(Array.isArray(current) ? current : []),
    ...(Array.isArray(data.superseded_source_ids)
      ? data.superseded_source_ids
      : []),
  ];
  return [
    ...new Set(
      values.flatMap((value) => {
        const row = record(value);
        const id =
          typeof value === "string"
            ? value
            : (row.source_id ?? row.id ?? row.reference);
        return typeof id === "string" ? [id] : [];
      }),
    ),
  ];
}

export function sourceDisplayTitle(source: Row, caseTitle: string): string {
  if (source.source_type === "director_message") return "Director request";
  const filename = record(source.metadata).filename;
  if (typeof filename === "string" && filename.trim())
    return friendlyTitle(filename);
  return source.source_type === "gmail"
    ? `Email · ${friendlyTitle(caseTitle)}`
    : friendlyTitle(caseTitle);
}

function SourcePaper({
  source,
  snapshot,
  caseTitle,
}: {
  source: Row;
  snapshot: FinanceSnapshot;
  caseTitle: string;
}) {
  const path = textValue(source.artifact_path, "");
  const identity = JSON.stringify([
    snapshot.organization.id,
    snapshot.run.id,
    source.id,
    source.version,
    path,
  ]);
  const [receipt, setReceipt] = useState<{
    identity: string;
    status: "loading" | "ready" | "error";
    text?: string;
    failure?: string;
  } | null>(null);
  // Props may change before an effect runs. Never label the previous fetch's
  // text/error as the newly requested document, even if a parent reuses its key.
  const matching = receipt?.identity === identity;
  const text =
    matching && receipt.status === "ready" ? (receipt.text ?? null) : null;
  const failure =
    matching && receipt.status === "error" ? receipt.failure : null;
  const loading = Boolean(path) && (!matching || receipt.status === "loading");
  useEffect(() => {
    let current = true;
    if (!path) return;
    setReceipt({ identity, status: "loading" });
    if (!path.startsWith(`${snapshot.organization.id}/${snapshot.run.id}/`)) {
      setReceipt({
        identity,
        status: "error",
        failure: "This document does not belong to the selected event run.",
      });
      return;
    }
    void browserSupabase()
      .storage.from("finance-artifacts")
      .download(path)
      .then(async (result) => {
        if (result.error || !result.data)
          throw new Error(
            "Source unavailable. Refresh the case or check event access.",
          );
        if (result.data.size > 4 * 1024 * 1024)
          throw new Error(
            "This source is too large for the preview. Use the source register to download it.",
          );
        const content = await result.data.text();
        let visible = content;
        try {
          const value: unknown = JSON.parse(content);
          visible = sourceDocumentText(displayRecord(value));
        } catch {
          /* Plain-text sources render as text, never HTML. */
        }
        if (current)
          setReceipt({
            identity,
            status: "ready",
            text:
              visible.slice(0, 100000) +
              (visible.length > 100000
                ? "\n[Preview truncated. Download the source for the full record.]"
                : ""),
          });
      })
      .catch((error) => {
        if (current)
          setReceipt({
            identity,
            status: "error",
            failure:
              error instanceof Error ? error.message : "Source unavailable.",
          });
      });
    return () => {
      current = false;
    };
  }, [identity, path, snapshot.organization.id, snapshot.run.id]);
  return (
    <article
      className="source-paper-live"
      data-source-id={textValue(source.id)}
      data-source-version={textValue(source.version)}
      data-source-load-state={
        !path ? "unavailable" : matching ? receipt.status : "loading"
      }
    >
      <header>
        <FileText size={20} />
        <div>
          <h2>{sourceDisplayTitle(source, caseTitle)}</h2>
          <span>
            {["demo_bundle", "guided_demo"].includes(
              textValue(source.source_type),
            )
              ? "Practice document"
              : source.source_type === "gmail"
                ? "Email"
                : source.source_type === "director_message"
                  ? "Message"
                  : "Document"}{" "}
            · Version {textValue(source.version)}
          </span>
        </div>
      </header>
      {loading && (
        <p role="status">
          <LoaderCircle className="spin" size={16} /> Reading source…
        </p>
      )}
      {failure && <p role="alert">{failure}</p>}
      {text !== null && (
        <div
          className="source-content"
          data-loaded-source-id={textValue(source.id)}
          data-loaded-source-version={textValue(source.version)}
        >
          <ReadableText text={text} />
        </div>
      )}
      {!path && <p>No stored document preview is available.</p>}
      <details>
        <summary>Source provenance</summary>
        <pre>{JSON.stringify(displayRecord(source), null, 2)}</pre>
      </details>
    </article>
  );
}

export function CaseWorkspace({
  item,
  snapshot,
  onBack,
  onReview,
  busy,
  canWork,
  decisions,
  evidenceForm,
  conversationForm,
}: {
  item: FinanceSnapshot["cases"][number];
  snapshot: FinanceSnapshot;
  onBack: () => void;
  onReview: () => void;
  busy: boolean;
  canWork: boolean;
  decisions: ReactNode;
  evidenceForm: ReactNode;
  conversationForm?: ReactNode;
}) {
  const ids = caseSourceIds(item.data);
  const sources = ids.flatMap((id) =>
    snapshot.source_items.filter((source) => source.id === id),
  );
  const superseded = Array.isArray(item.data.superseded_source_ids)
    ? item.data.superseded_source_ids
    : [];
  const [selected, setSelected] = useState("");
  const source = sources.find((row) => row.id === selected) ?? sources[0];
  const finding = record(item.data.finding);
  const action = record(finding.proposed_action);
  const responses = Array.isArray(item.data.director_responses)
    ? item.data.director_responses.filter(
        (value) =>
          typeof record(value).message === "string" &&
          String(record(value).message).trim(),
      )
    : [];
  // Stored conversation history is appended by the guarded persistence RPC.
  // Compare recorded case versions; prose never changes financial state here.
  const latestResponse = responses.length
    ? record(responses[responses.length - 1])
    : null;
  const reviewVersion = record(finding.provenance).source_case_version;
  const responseVersion = record(
    latestResponse?.provenance,
  ).source_case_version;
  const newerResponse =
    Boolean(latestResponse) &&
    (!finding.explanation ||
      (typeof reviewVersion === "number" &&
        Number.isSafeInteger(reviewVersion) &&
        typeof responseVersion === "number" &&
        Number.isSafeInteger(responseVersion) &&
        responseVersion > reviewVersion));
  const blockers = Array.isArray(finding.blocking_requirements)
    ? finding.blocking_requirements
    : [];
  const jobs = snapshot.jobs.filter(
    (job) => record(job.payload).case_id === item.id || job.case_id === item.id,
  );
  const events = snapshot.activity.filter(
    (event) => event.payload.case_id === item.id,
  );
  const running = jobs.some((job) => job.status === "running");
  const queued = jobs.some((job) => job.status === "queued");
  const amount =
    typeof action.amount_minor === "string" && /^\d+$/.test(action.amount_minor)
      ? action.amount_minor
      : null;
  return (
    <section className="live-case-workspace">
      <header className="live-case-heading">
        <div>
          <button className="text-button" onClick={onBack}>
            <ArrowLeft size={15} /> All work
          </button>
          <h1>{friendlyTitle(item.title)}</h1>
          <p>
            Version {item.version} · Updated {dateTime(item.updated_at)}
          </p>
        </div>
        <span className="badge neutral">
          {item.status.replaceAll("_", " ")}
        </span>
      </header>
      <div className="live-case-layout">
        <div className="live-case-evidence">
          <nav className="live-source-tabs" aria-label="Case documents">
            {sources.map((row) => (
              <button
                key={textValue(row.id)}
                data-source-id={textValue(row.id)}
                data-source-version={textValue(row.version)}
                aria-pressed={selected !== "activity" && source?.id === row.id}
                onClick={() => setSelected(textValue(row.id))}
              >
                {sourceDisplayTitle(row, item.title)} · v
                {textValue(row.version)}
                {superseded.includes(row.id) ? " · Earlier" : ""}
              </button>
            ))}
            <button
              aria-pressed={selected === "activity"}
              onClick={() => setSelected("activity")}
            >
              Activity
            </button>
          </nav>
          {selected === "activity" ? (
            <section className="source-paper-live">
              <h2>Case activity</h2>
              {events.length ? (
                <ol className="case-timeline">
                  {events.map((event) => (
                    <li key={event.id}>
                      <strong>{event.event_type.replaceAll("_", " ")}</strong>
                      <time>{dateTime(event.created_at)}</time>
                      <details>
                        <summary>Inspect recorded event</summary>
                        <pre>
                          {JSON.stringify(
                            displayRecord(event.payload),
                            null,
                            2,
                          )}
                        </pre>
                      </details>
                    </li>
                  ))}
                </ol>
              ) : (
                <p>No case-linked activity has been recorded.</p>
              )}
            </section>
          ) : source ? (
            <SourcePaper
              key={`${textValue(source.id)}:${textValue(source.version)}`}
              source={source}
              snapshot={snapshot}
              caseTitle={item.title}
            />
          ) : (
            <section className="source-paper-live">
              <h2>Source evidence</h2>
              <p>No document is linked to this case yet. Add evidence below.</p>
            </section>
          )}
          <details className="case-evidence-action">
            <summary>Add a document</summary>
            {evidenceForm}
          </details>
        </div>
        <aside className="live-case-decision">
          <header className="decision-finney-live">
            <img src="/brand/finney.svg" alt="" />
            <span>Finney</span>
          </header>
          <h2>
            {running
              ? "Working on this case."
              : queued
                ? "Review queued."
                : newerResponse
                  ? "Latest response"
                  : finding.decision
                    ? "Review ready"
                    : "Ready for review"}
          </h2>
          {running && (
            <p className="case-progress" role="status">
              <LoaderCircle className="spin" size={16} /> The agent is working.
              You can keep using the desk.
            </p>
          )}
          {newerResponse && latestResponse && (
            <section className="case-latest-response">
              <p className="case-chronology-label">
                {typeof responseVersion === "number"
                  ? `Based on case v${responseVersion} · Stored agent response`
                  : "Stored agent response"}
              </p>
              <DirectorResponses
                responses={[latestResponse]}
                heading="Finney’s latest reply"
                collapseLong
              />
            </section>
          )}
          {newerResponse && decisions}
          <section
            className={
              newerResponse
                ? "prepared-case-review earlier-prepared-review"
                : "prepared-case-review"
            }
          >
            {newerResponse && Boolean(finding.explanation) && (
              <h3 className="case-chronology-label">
                Earlier prepared review · based on case v{String(reviewVersion)}
              </h3>
            )}
            {typeof finding.explanation === "string" && (
              <details
                className="case-review-reasoning"
                open={finding.explanation.length < 600}
              >
                <summary>Read Finney’s review</summary>
                <ReadableText
                  className="case-explanation"
                  text={finding.explanation}
                />
              </details>
            )}
            {amount !== null && (
              <dl className="case-amount">
                <div>
                  <dt>
                    {newerResponse
                      ? "Earlier proposed amount"
                      : "Proposed amount"}
                  </dt>
                  <dd>
                    {formatMoney(
                      amount,
                      textValue(action.currency, snapshot.run.currency),
                    )}
                  </dd>
                </div>
                {Boolean(
                  action.payee || action.recipient || action.destination,
                ) && (
                  <div>
                    <dt>To</dt>
                    <dd>
                      {textValue(
                        action.payee ?? action.recipient ?? action.destination,
                      )}
                    </dd>
                  </div>
                )}
              </dl>
            )}
            {typeof finding.clarification === "string" && (
              <ReadableText
                className="case-clarification"
                text={finding.clarification}
              />
            )}
            {blockers.length > 0 && (
              <section className="case-blockers">
                <h3>
                  {newerResponse
                    ? "Requirements in that review"
                    : "What needs attention"}
                </h3>
                <ul>
                  {blockers.map((value, index) => {
                    const row = record(value);
                    return (
                      <li key={index}>
                        <strong>
                          {textValue(row.stage, "Review").replaceAll("_", " ")}
                        </strong>
                        <span>
                          {textValue(
                            row.requirement ?? row.reason ?? row.description,
                            "Inspect the recorded requirement",
                          ).replaceAll("_", " ")}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </section>
            )}
            {Boolean(finding.verification) && (
              <p className="muted">Agent review · awaiting verification</p>
            )}
          </section>
          {!newerResponse && decisions}
          <button
            className="primary"
            disabled={!canWork || busy || running || queued}
            onClick={onReview}
          >
            {running || queued ? "Review in progress" : "Request review"}
          </button>
          {!newerResponse ? (
            <DirectorResponses responses={item.data.director_responses} />
          ) : responses.length > 1 ? (
            <details className="case-response-history">
              <summary>Earlier replies ({responses.length - 1})</summary>
              <DirectorResponses responses={responses.slice(0, -1)} />
            </details>
          ) : null}
          {conversationForm && (
            <details className="case-conversation">
              <summary>Ask about this case</summary>
              {conversationForm}
            </details>
          )}
          <details className="case-provenance">
            <summary>Decision record and provenance</summary>
            <pre>{JSON.stringify(displayRecord(item.data), null, 2)}</pre>
          </details>
        </aside>
      </div>
    </section>
  );
}

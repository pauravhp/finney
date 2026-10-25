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
import { DirectorResponses } from "@/components/director-responses";

type Row = Record<string, unknown>;
function record(value: unknown): Row {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Row)
    : {};
}
export function caseSourceIds(data: Row): string[] {
  const values =
    data.source_ids ?? data.source_refs ?? data.sources ?? data.evidence;
  if (!Array.isArray(values)) return [];
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

function SourcePaper({
  source,
  snapshot,
}: {
  source: Row;
  snapshot: FinanceSnapshot;
}) {
  const [text, setText] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const path = textValue(source.artifact_path, "");
  const metadata = record(source.metadata);
  useEffect(() => {
    let current = true;
    setText(null);
    setFailure(null);
    if (!path) return;
    if (!path.startsWith(`${snapshot.organization.id}/${snapshot.run.id}/`)) {
      setFailure("This document does not belong to the selected event run.");
      return;
    }
    setLoading(true);
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
          const row = record(value);
          const candidate =
            row.text ?? row.body ?? row.content ?? row.description;
          visible =
            typeof candidate === "string"
              ? candidate
              : JSON.stringify(displayRecord(value), null, 2);
        } catch {
          /* Plain-text sources render as text, never HTML. */
        }
        if (current)
          setText(
            visible.slice(0, 100000) +
              (visible.length > 100000
                ? "\n[Preview truncated. Download the source for the full record.]"
                : ""),
          );
      })
      .catch((error) => {
        if (current)
          setFailure(
            error instanceof Error ? error.message : "Source unavailable.",
          );
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [path, source.version, snapshot.organization.id, snapshot.run.id]);
  return (
    <article
      className="source-paper-live"
      data-source-id={textValue(source.id)}
      data-source-version={textValue(source.version)}
    >
      <header>
        <FileText size={20} />
        <div>
          <h2>
            {textValue(
              metadata.filename ?? source.external_id,
              "Source document",
            )}
          </h2>
          <span>
            {textValue(source.source_type)} · Version{" "}
            {textValue(source.version)}
          </span>
        </div>
      </header>
      {loading && (
        <p role="status">
          <LoaderCircle className="spin" size={16} /> Reading source…
        </p>
      )}
      {failure && <p role="alert">{failure}</p>}
      {text !== null && <pre className="source-content">{text}</pre>}
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
  const sources = snapshot.source_items.filter((source) =>
    ids.includes(textValue(source.id, "")),
  );
  const [selected, setSelected] = useState("");
  const source = sources.find((row) => row.id === selected) ?? sources[0];
  const finding = record(item.data.finding);
  const action = record(finding.proposed_action);
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
          <h1>{item.title}</h1>
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
                {textValue(record(row.metadata).filename, "Source")} · v
                {textValue(row.version)}
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
            <SourcePaper key={`${textValue(source.id)}:${textValue(source.version)}`} source={source} snapshot={snapshot} />
          ) : (
            <section className="source-paper-live">
              <h2>Source evidence</h2>
              <p>No document is linked to this case yet. Add evidence below.</p>
            </section>
          )}
          <details className="case-evidence-action">
            <summary>Add evidence / revise document</summary>
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
                : textValue(finding.decision, "Ready for review").replaceAll(
                    "_",
                    " ",
                  )}
          </h2>
          {running && (
            <p className="case-progress" role="status">
              <LoaderCircle className="spin" size={16} /> The agent is working.
              You can keep using the desk.
            </p>
          )}
          {typeof finding.explanation === "string" && (
            <p className="case-explanation">{finding.explanation}</p>
          )}
          {amount !== null && (
            <dl className="case-amount">
              <div>
                <dt>Proposed amount</dt>
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
            <p className="case-clarification">{finding.clarification}</p>
          )}
          {blockers.length > 0 && (
            <section className="case-blockers">
              <h3>What needs attention</h3>
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
            <p className="muted">
              Agent recommendation ·{" "}
              {textValue(finding.verification).replaceAll("_", " ")}
            </p>
          )}
          {decisions}
          <button
            className="primary"
            disabled={!canWork || busy}
            onClick={onReview}
          >
            {running || queued ? "Queue another review" : "Request review"}
          </button>
          <DirectorResponses responses={item.data.director_responses} />
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

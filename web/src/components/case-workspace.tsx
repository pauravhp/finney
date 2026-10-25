"use client";

import { useEffect, useState, type ReactNode } from "react";
import { ArrowLeft, ArrowRight, FileText, LoaderCircle } from "lucide-react";
import { browserSupabase } from "@/lib/supabase/browser";
import {
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
import { FinneyCharacter, caseWorkState } from "@/components/finney-companion";

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
  if (source.source_type === "gmail") return "Email";
  return /invoice/i.test(caseTitle)
    ? "Invoice"
    : /receipt|reimbursement/i.test(caseTitle)
      ? "Receipt"
      : "Document";
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
    caseTitle,
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
          visible = sourceDocumentText(displayRecord(value), caseTitle);
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
  }, [identity, path, snapshot.organization.id, snapshot.run.id, caseTitle]);
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
  onViewBudget,
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
  onViewBudget?: () => void;
}) {
  const ids = caseSourceIds(item.data);
  // Director requests are retained in the conversation and backend audit, never
  // mislabeled as invoice/source tabs. Superseded documents remain inspectable.
  const linked = ids.flatMap((id) =>
    snapshot.source_items.filter(
      (source) => source.id === id && source.source_type !== "director_message",
    ),
  );
  const superseded = Array.isArray(item.data.superseded_source_ids)
    ? item.data.superseded_source_ids
    : [];
  const sources = [
    ...linked.filter((source) => !superseded.includes(source.id)),
    ...linked.filter((source) => superseded.includes(source.id)),
  ];
  const [selected, setSelected] = useState("");
  const source = sources.find((source) => source.id === selected) ?? sources[0];
  const finding = record(item.data.finding);
  const action = record(finding.proposed_action);
  const responses = Array.isArray(item.data.director_responses)
    ? item.data.director_responses.filter(
        (value) =>
          typeof record(value).message === "string" &&
          String(record(value).message).trim(),
      )
    : [];
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
        typeof responseVersion === "number" &&
        responseVersion > reviewVersion));
  const storedState = caseWorkState(snapshot, item.id);
  const state = busy ? "running" : storedState;
  const working =
    state === "running" || state === "queued" || state === "finishing";
  const hasResult = state === "completed";
  const title = {
    ready: "Ready when you are.",
    queued: "Got it.",
    running: "On it.",
    finishing: "Finishing up.",
    attention: "Your call.",
    failed: "I need a hand.",
    completed: "Here’s what I found.",
  }[state];
  const amount =
    typeof action.amount_minor === "string" && /^\d+$/.test(action.amount_minor)
      ? action.amount_minor
      : null;
  const noun = /invoice/i.test(item.title)
    ? "invoice"
    : /receipt|reimbursement/i.test(item.title)
      ? "receipt"
      : "document";
  const blockers = Array.isArray(finding.blocking_requirements)
    ? finding.blocking_requirements
    : [];
  return (
    <section
      className="live-case-workspace companion-case-workspace"
      data-case-state={state}
    >
      <header className="live-case-heading">
        <div>
          <button className="text-button" onClick={onBack}>
            <ArrowLeft size={15} />
            Back
          </button>
          <h1>{friendlyTitle(item.title)}</h1>
        </div>
      </header>
      <div className="live-case-layout">
        <div className="live-case-evidence">
          {sources.length > 1 && (
            <nav className="live-source-tabs" aria-label="Case documents">
              {sources.map((row, index) => (
                <button
                  key={textValue(row.id)}
                  data-source-id={textValue(row.id)}
                  data-source-version={textValue(row.version)}
                  aria-pressed={source?.id === row.id}
                  onClick={() => setSelected(textValue(row.id))}
                >
                  {superseded.includes(row.id)
                    ? `Previous ${noun}`
                    : index === 0
                      ? noun.charAt(0).toUpperCase() + noun.slice(1)
                      : sourceDisplayTitle(row, item.title)}
                </button>
              ))}
            </nav>
          )}
          {source ? (
            <SourcePaper
              key={`${textValue(source.id)}:${textValue(source.version)}`}
              source={source}
              snapshot={snapshot}
              caseTitle={item.title}
            />
          ) : (
            <section className="source-paper-live">
              <h2>No document attached</h2>
              <p>Add an invoice or receipt to get started.</p>
            </section>
          )}
          <details className="case-evidence-action">
            <summary>Add a document</summary>
            {evidenceForm}
          </details>
        </div>
        <aside
          className="live-case-decision companion-case-panel"
          aria-label="Finney’s work"
        >
          <header
            className="case-character-heading"
            data-tutorial={working ? "finney-working" : undefined}
            tabIndex={working ? -1 : undefined}
          >
            <FinneyCharacter state={state} />
            <h2 aria-live="polite">{title}</h2>
          </header>
          {state === "failed" && (
            <p role="status">
              I couldn’t finish this request. Please try again.
            </p>
          )}
          {hasResult && newerResponse && latestResponse && (
            <section className="case-latest-response">
              <DirectorResponses
                responses={[latestResponse]}
                heading=""
                collapseLong
              />
            </section>
          )}
          {hasResult &&
            !newerResponse &&
            typeof finding.explanation === "string" && (
              <DirectorResponses
                responses={[{ message: finding.explanation }]}
                heading=""
                collapseLong
              />
            )}
          {hasResult && !newerResponse && amount !== null && (
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
          {hasResult && !newerResponse && blockers.length > 0 && (
            <section className="case-blockers">
              <h3>Before we go ahead</h3>
              <ul>
                {blockers.map((value, index) => {
                  const blocker = record(value);
                  return (
                    <li key={index}>
                      <strong>
                        {textValue(blocker.stage, "Review").replaceAll(
                          "_",
                          " ",
                        )}
                      </strong>
                      <span>
                        {textValue(
                          blocker.requirement ??
                            blocker.reason ??
                            blocker.description,
                          "More evidence is needed.",
                        ).replaceAll("_", " ")}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
          {decisions}
          {hasResult && onViewBudget ? (
            <button
              className="primary case-main-action"
              data-tutorial="view-budget"
              onClick={onViewBudget}
            >
              See budget
              <ArrowRight size={16} />
            </button>
          ) : (
            <button
              className="primary case-main-action"
              data-tutorial="review-case"
              disabled={!canWork || working}
              onClick={onReview}
            >
              {working
                ? "Working…"
                : state === "failed"
                  ? "Try again"
                  : hasResult
                    ? "Review again"
                    : `Check ${noun}`}
              <ArrowRight size={16} />
            </button>
          )}
          {hasResult && onViewBudget && (
            <button
              className="text-button case-check-again"
              data-tutorial="review-case"
              disabled={!canWork || working}
              onClick={onReview}
            >
              Check again
            </button>
          )}
          {(conversationForm ||
            responses.length > 1 ||
            typeof item.data.director_request === "string") && (
            <details className="case-conversation">
              <summary>Ask Finney</summary>
              {typeof item.data.director_request === "string" && (
                <div className="case-request">
                  <strong>You</strong>
                  <p>{item.data.director_request}</p>
                </div>
              )}
              {responses.length > 1 && (
                <DirectorResponses
                  responses={responses.slice(0, -1)}
                  heading="Earlier conversation"
                  collapseLong
                />
              )}
              {conversationForm}
            </details>
          )}
        </aside>
      </div>
    </section>
  );
}

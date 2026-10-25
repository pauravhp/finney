"use client";

import { useEffect, useId, useState } from "react";
import { ArrowLeft, ArrowRight, ArrowUp, ArrowUpRight } from "lucide-react";
import { formatMoney, textValue, type FinanceSnapshot } from "@/lib/contracts";
import { friendlyTitle } from "@/components/readable-text";
import {
  photoBoothContext,
  shouldSubmitScenarioPrompt,
} from "@/lib/photo-booth-scenario";
import { DirectorResponses } from "@/components/director-responses";

type Row = Record<string, unknown>;
export type CompanionKind =
  | "ready"
  | "queued"
  | "running"
  | "finishing"
  | "attention"
  | "failed"
  | "completed";
export type CompanionState = {
  kind: CompanionKind;
  title: string;
  detail: string;
  caseId?: string;
  action: "case" | "budget" | "approvals";
  actionLabel: string;
  amount?: string;
  currency?: string;
};
function row(value: unknown): Row {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Row)
    : {};
}
export function caseWorkState(
  snapshot: FinanceSnapshot,
  caseId: string,
): CompanionKind {
  const jobs = snapshot.jobs
    .filter(
      (job) =>
        (job.case_id === caseId || row(job.payload).case_id === caseId) &&
        ["director_message", "review_case"].includes(String(job.command_type)),
    )
    .sort(
      (a, b) =>
        (Date.parse(String(b.created_at)) || 0) -
        (Date.parse(String(a.created_at)) || 0),
    );
  if (jobs.some((job) => job.status === "running")) return "running";
  if (jobs.some((job) => job.status === "queued")) return "queued";
  if (
    jobs[0] &&
    ["failed", "blocked", "cancelled"].includes(String(jobs[0].status))
  )
    return "failed";
  const item = snapshot.cases.find((item) => item.id === caseId);
  const finding = row(item?.data.finding);
  const replies = Array.isArray(item?.data.director_responses)
    ? item.data.director_responses
        .map(row)
        .filter(
          (reply) => typeof reply.message === "string" && reply.message.trim(),
        )
    : [];
  const hasFinding =
    typeof finding.explanation === "string" && finding.explanation.trim();
  if (jobs[0]?.status === "completed") {
    const jobId = jobs[0].id;
    const matched =
      typeof jobId === "string" &&
      ((hasFinding && row(finding.provenance).job_id === jobId) ||
        replies.some(
          (reply) => (reply.job_id ?? row(reply.provenance).job_id) === jobId,
        ));
    return matched ? "completed" : "finishing";
  }
  if (hasFinding || replies.length) return "completed";
  return "ready";
}
export function companionState(
  snapshot: FinanceSnapshot | null,
  caseId?: string,
): CompanionState {
  if (!snapshot)
    return {
      kind: "queued",
      title: "One moment.",
      detail: "Opening your event",
      action: "case",
      actionLabel: "Open the desk",
    };
  const pendingApproval = snapshot.approvals.find(
    (proposal) =>
      proposal.status === "pending" &&
      (!caseId || proposal.action.case_id === caseId),
  );
  if (pendingApproval)
    return {
      kind: "attention",
      title: "One for you.",
      detail: textValue(
        pendingApproval.action.title ?? pendingApproval.action.payee,
        "Payment proposal",
      ),
      caseId:
        typeof pendingApproval.action.case_id === "string"
          ? pendingApproval.action.case_id
          : undefined,
      action: "approvals",
      actionLabel: "Review proposal",
      amount:
        typeof pendingApproval.action.amount_minor === "string"
          ? pendingApproval.action.amount_minor
          : undefined,
      currency: textValue(
        pendingApproval.action.currency,
        snapshot.run.currency,
      ),
    };
  const pendingBudget = !caseId
    ? snapshot.budget.decisions.find(
        (decision) => decision.status === "pending",
      )
    : null;
  if (pendingBudget)
    return {
      kind: "attention",
      title: "Your call.",
      detail: `${textValue(pendingBudget.name ?? pendingBudget.new_name, "Event")} budget`,
      action: "budget",
      actionLabel: "Review budget",
      amount:
        typeof pendingBudget.allocated_minor === "string"
          ? pendingBudget.allocated_minor
          : undefined,
      currency: textValue(pendingBudget.currency, snapshot.run.currency),
    };
  const active = snapshot.jobs.find(
    (job) =>
      ["running", "queued"].includes(String(job.status)) &&
      typeof job.case_id === "string",
  );
  const orderedCases = [...snapshot.cases].sort(
    (a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at),
  );
  const guidedCase =
    photoBoothContext(snapshot)?.caseId ??
    snapshot.run.scenario?.steps?.find((step) => step.id === "catch")?.case_id;
  const item =
    orderedCases.find((item) => item.id === caseId) ??
    orderedCases.find((item) => item.id === active?.case_id) ??
    orderedCases.find((item) => item.id === guidedCase) ??
    orderedCases.find((item) => item.status === "needs_review") ??
    orderedCases[0];
  if (!item)
    return {
      kind: "ready",
      title: "Ready when you are.",
      detail: "What needs a look?",
      action: "case",
      actionLabel: "Ask Finney",
    };
  const kind = caseWorkState(snapshot, item.id);
  const titles = {
    ready: "One for you.",
    queued: "Got it.",
    running: "On it.",
    finishing: "Finishing up.",
    attention: "Your call.",
    failed: "I need a hand.",
    completed: "An update for you.",
  };
  return {
    kind,
    title: titles[kind],
    detail:
      photoBoothContext(snapshot)?.caseId === item.id
        ? "Can we afford the photo booth?"
        : friendlyTitle(item.title),
    caseId: item.id,
    action: "case",
    actionLabel:
      kind === "completed"
        ? "Open the update"
        : kind === "failed"
          ? "Open the request"
          : photoBoothContext(snapshot)?.caseId === item.id
            ? "Open the documents"
            : "Take a look",
  };
}
export function FinneyCharacter({
  state = "ready",
  listening = false,
  className = "",
}: {
  state?: CompanionKind;
  listening?: boolean;
  className?: string;
}) {
  const clip = useId().replaceAll(":", "");
  const pose = listening
    ? "looking"
    : {
        ready: "idle",
        queued: "looking",
        running: "working",
        finishing: "working",
        attention: "attention",
        failed: "blocked",
        completed: "success",
      }[state];
  return (
    <>
      <link rel="stylesheet" href="/brand/companion.css" precedence="default" />
      <svg
        className={`finney companion-mascot ${className}`}
        data-pose={pose}
        viewBox="0 0 180 190"
        aria-hidden="true"
      >
        <defs>
          <clipPath id={clip}>
            <path d="M48 30H131Q144 30 144 45V147L132 139L120 150L107 140L94 152L81 140L67 151L55 141L40 150V44Q40 30 48 30Z" />
          </clipPath>
        </defs>
        <g className="finney-shadow">
          <ellipse cx="93" cy="173" rx="37" ry="4" />
        </g>
        <g className="paper-rig">
          <g className="arm arm-left">
            <path d="M44 85Q20 77 20 94Q19 107 42 112Z" />
          </g>
          <g className="arm arm-right">
            <path d="M140 84Q160 60 165 73Q173 90 143 108Z" />
          </g>
          <g className="paper-body">
            <path
              className="paper"
              d="M48 30H131Q144 30 144 45V147L132 139L120 150L107 140L94 152L81 140L67 151L55 141L40 150V44Q40 30 48 30Z"
            />
            <path
              className="curl"
              d="M122 30H131Q144 30 144 45V53Q130 53 122 30Z"
            />
            <g clipPath={`url(#${clip})`} className="print-lines">
              <path d="M63 115H119M72 123H111" />
              <path className="scan-line" d="M54 108H132" />
            </g>
            <g className="face">
              <g className="brows">
                <path d="M66 63L79 61M108 61L121 63" />
              </g>
              <g className="eyes">
                <g className="left-eye">
                  <rect x="66" y="69" width="13" height="22" rx="6.5" />
                </g>
                <g className="right-eye">
                  <rect x="108" y="69" width="13" height="22" rx="6.5" />
                </g>
              </g>
              <path className="mouth smile" d="M85 100Q94 110 103 100" />
              <path className="mouth puzzled" d="M86 104Q94 99 102 104" />
              <path className="mouth sleepy" d="M89 104H99" />
            </g>
          </g>
        </g>
        <g className="work-paper">
          <path d="M14 45H34V71L29 67L24 71L19 67L14 71Z" />
          <path d="M19 51H29M19 57H27" />
        </g>
        <g className="success-check">
          <circle cx="143" cy="35" r="18" />
          <path d="M135 35L141 41L152 29" />
        </g>
      </svg>
    </>
  );
}
export type CompanionCommand = {
  jobId: string;
  type: string;
  caseId: string | null;
};
export function replyForCompanionCommand(
  snapshot: FinanceSnapshot | null,
  command: CompanionCommand | null,
) {
  if (!snapshot || !command || command.type !== "director_message") return null;
  const job = snapshot.jobs.find((job) => job.id === command.jobId);
  if (
    !job ||
    job.status !== "completed" ||
    job.command_type !== "director_message"
  )
    return null;
  if (command.caseId && job.case_id !== command.caseId) return null;
  const caseId =
    command.caseId ?? (typeof job.case_id === "string" ? job.case_id : null);
  const item = snapshot.cases.find((item) => item.id === caseId);
  if (!Array.isArray(item?.data.director_responses)) return null;
  return (
    item.data.director_responses
      .map(row)
      .find(
        (reply) =>
          (reply.job_id ?? row(reply.provenance).job_id) === command.jobId &&
          typeof reply.message === "string" &&
          reply.message.trim(),
      ) ?? null
  );
}
type Question = {
  message: string;
  caseId: string | null;
  previousJobId: string | null;
  replyIds: string[];
  replyCount: number;
  jobId: string | null;
};
export function FinneyCompanion({
  snapshot,
  onOpenCase,
  onAsk,
  onViewBudget,
  onViewApprovals,
  onExpand,
  busy = false,
  canWork = true,
  caseId,
  lastCommand = null,
}: {
  snapshot: FinanceSnapshot | null;
  onOpenCase: (caseId: string) => void;
  onAsk: (
    message: string,
    caseId?: string,
  ) => Promise<boolean | void> | boolean | void;
  onViewBudget?: () => void;
  onViewApprovals?: () => void;
  onExpand?: () => void;
  busy?: boolean;
  canWork?: boolean;
  caseId?: string;
  lastCommand?: CompanionCommand | null;
}) {
  const [message, setMessage] = useState("");
  const [listening, setListening] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [question, setQuestion] = useState<Question | null>(null);
  const photo = photoBoothContext(snapshot);
  const [introSeen, setIntroSeen] = useState(false);
  useEffect(() => {
    if (!photo) {
      setIntroSeen(true);
      return;
    }
    try {
      setIntroSeen(localStorage.getItem(photo.storageKey) === "seen");
    } catch {
      setIntroSeen(false);
    }
  }, [photo?.storageKey]);
  const scopeKey = snapshot
    ? `${snapshot.organization.id}:${snapshot.run.id}`
    : "";
  useEffect(() => {
    setQuestion(null);
    setError("");
    setMessage("");
  }, [scopeKey]);
  // A server-issued command receipt is the only association between this prompt
  // and its answer. Never guess from a newer unrelated or concurrent response.
  useEffect(() => {
    if (
      !question ||
      question.jobId ||
      !lastCommand ||
      lastCommand.type !== "director_message" ||
      lastCommand.jobId === question.previousJobId ||
      lastCommand.caseId !== question.caseId
    )
      return;
    setQuestion((current) =>
      current ? { ...current, jobId: lastCommand.jobId } : null,
    );
  }, [lastCommand, question]);
  const command = question?.jobId
    ? {
        jobId: question.jobId,
        type: "director_message",
        caseId: question.caseId,
      }
    : null;
  const result = replyForCompanionCommand(snapshot, command);
  const resultId = result
    ? String(result.id ?? result.job_id ?? row(result.provenance).job_id)
    : "";
  const answer =
    result && question && !question.replyIds.includes(resultId) ? result : null;
  const questionJob = question?.jobId
    ? snapshot?.jobs.find((job) => job.id === question.jobId)
    : null;
  const failed =
    questionJob &&
    ["failed", "blocked", "cancelled"].includes(String(questionJob.status));
  const waiting = Boolean(question && !answer && !failed);
  const state = companionState(snapshot, caseId);
  const active = busy || sending || waiting;
  const shownKind: CompanionKind = failed
    ? "failed"
    : answer
      ? "completed"
      : questionJob?.status === "completed" && !answer
        ? "finishing"
        : active
          ? "running"
          : state.kind;
  const title = failed
    ? "I need a hand."
    : answer
      ? "Here’s the update."
      : shownKind === "finishing"
        ? "Finishing up."
        : active
          ? "On it."
          : listening
            ? "I’m listening."
            : state.title;
  const inputId = useId();
  const open = () => {
    if (state.action === "budget" && onViewBudget) onViewBudget();
    else if (state.action === "approvals" && onViewApprovals) onViewApprovals();
    else if (state.caseId) onOpenCase(state.caseId);
    else document.getElementById(inputId)?.focus();
  };
  const leaveIntro = (prefill: boolean) => {
    setIntroSeen(true);
    if (photo)
      try {
        localStorage.setItem(photo.storageKey, "seen");
      } catch {
        /* Optional preference only. */
      }
    if (prefill && photo) setMessage(photo.prompt);
    requestAnimationFrame(() => document.getElementById(inputId)?.focus());
  };
  if (photo && !introSeen)
    return (
      <section
        className="finney-companion photo-scenario-intro"
        aria-label="Practice event introduction"
      >
        <header className="companion-header">
          <span>
            Finney <small>/ {photo.title}</small>
          </span>
        </header>
        <div className="companion-character">
          <FinneyCharacter state="ready" />
        </div>
        <h2 className="companion-title">Can we afford the photo booth?</h2>
        <p>{photo.brief}</p>
        <p>
          The team thinks sponsorship will cover it. The latest invoices,
          receipts and sponsor terms need a closer look.
        </p>
        <button
          className="companion-primary"
          disabled={!photo.ready}
          onClick={() => leaveIntro(true)}
        >
          {photo.ready ? "Start with a question" : "Preparing documents…"}
          <ArrowRight size={17} />
        </button>
        <button className="companion-back" onClick={() => leaveIntro(false)}>
          Skip introduction
        </button>
        <p className="photo-scenario-label">
          Private practice event · fictional documents
        </p>
      </section>
    );
  return (
    <section
      className={`finney-companion ${answer ? "has-answer" : ""} ${photo ? "photo-scenario" : ""}`}
      aria-label="Finney companion"
      data-state={shownKind}
    >
      <header className="companion-header">
        <span>
          Finney{" "}
          <small>
            /{" "}
            {snapshot?.run.scenario?.title ??
              snapshot?.organization.name ??
              "Your event"}
          </small>
        </span>
        {onExpand && (
          <button
            className="companion-expand"
            onClick={onExpand}
            aria-label="Open full desk"
          >
            <ArrowUpRight size={17} />
          </button>
        )}
      </header>
      <div className="companion-character">
        <FinneyCharacter
          state={shownKind}
          listening={listening && !active && !answer}
        />
      </div>
      <h2 className="companion-title" aria-live="polite">
        {title}
      </h2>
      {question ? (
        <div className="companion-conversation">
          <button
            className="companion-back"
            onClick={() => {
              setQuestion(null);
              setError("");
            }}
          >
            <ArrowLeft size={14} />
            Back to alert
          </button>
          {answer ? (
            <div className="companion-answer" aria-live="polite">
              <DirectorResponses responses={[answer]} heading="" />
            </div>
          ) : failed ? (
            <p className="companion-error" role="alert">
              I couldn’t finish that request. You can ask me to try again.
            </p>
          ) : (
            <p className="companion-question">{question.message}</p>
          )}
        </div>
      ) : (
        <div className="companion-task">
          <div className="companion-task-heading">
            <span>{state.detail}</span>
            {state.amount && (
              <strong>
                {formatMoney(state.amount, state.currency ?? "USD")}
              </strong>
            )}
          </div>
          <button
            className="companion-primary"
            data-tutorial="open-alert"
            onClick={open}
            disabled={
              !snapshot ||
              (!state.caseId && state.action === "case" && !canWork)
            }
          >
            {state.actionLabel}
            <ArrowRight size={17} />
          </button>
        </div>
      )}
      <form
        className="companion-composer"
        data-tutorial="ask-finney"
        onSubmit={async (event) => {
          event.preventDefault();
          if (!message.trim() || sending || !canWork) return;
          const askedCase = caseId ?? photo?.caseId ?? state.caseId ?? null;
          const replies = snapshot?.cases.find((item) => item.id === askedCase)
            ?.data.director_responses;
          const prior = Array.isArray(replies) ? replies.map(row) : [];
          setQuestion({
            message: message.trim(),
            caseId: askedCase,
            previousJobId: lastCommand?.jobId ?? null,
            replyIds: prior.map((reply) =>
              String(reply.id ?? reply.job_id ?? row(reply.provenance).job_id),
            ),
            replyCount: prior.length,
            jobId: null,
          });
          setSending(true);
          setError("");
          try {
            const accepted = await onAsk(
              message.trim(),
              askedCase ?? undefined,
            );
            if (accepted !== false) setMessage("");
            else {
              setQuestion((current) => (current?.jobId ? current : null));
              setError("I couldn’t queue that request. Please try again.");
            }
          } catch {
            setQuestion((current) => (current?.jobId ? current : null));
            setError("I couldn’t send that. Please try again.");
          } finally {
            setSending(false);
          }
        }}
      >
        <label className="sr-only" htmlFor={inputId}>
          Ask Finney
        </label>
        {photo ? (
          <textarea
            id={inputId}
            value={message}
            rows={6}
            maxLength={4000}
            placeholder="Ask Finney…"
            onFocus={() => setListening(true)}
            onBlur={() => setListening(false)}
            onChange={(event) => setMessage(event.target.value)}
            onKeyDown={(event) => {
              if (
                shouldSubmitScenarioPrompt(
                  event.key,
                  event.shiftKey,
                  event.nativeEvent.isComposing,
                  event.nativeEvent.keyCode,
                )
              ) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            disabled={!canWork || sending}
          />
        ) : (
          <input
            id={inputId}
            value={message}
            maxLength={4000}
            placeholder="Ask Finney…"
            autoComplete="off"
            onFocus={() => setListening(true)}
            onBlur={() => setListening(false)}
            onChange={(event) => setMessage(event.target.value)}
            disabled={!canWork || sending}
          />
        )}

        <button
          type="submit"
          aria-label="Send to Finney"
          disabled={!message.trim() || !canWork || sending}
        >
          <ArrowUp size={17} />
        </button>
      </form>
      {error && (
        <p className="companion-error" role="alert">
          {error}
        </p>
      )}
      {photo && !question && !message && (
        <button
          className="companion-back"
          onClick={() => {
            setMessage(photo.prompt);
            document.getElementById(inputId)?.focus();
          }}
        >
          Use the opening question
        </button>
      )}
      <footer className="companion-shortcuts">
        {onViewBudget && <button onClick={onViewBudget}>Budget</button>}
        <button
          onClick={() => {
            setMessage("What sponsorship is still outstanding?");
            document.getElementById(inputId)?.focus();
          }}
        >
          Sponsors
        </button>
      </footer>
    </section>
  );
}

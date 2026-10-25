"use client";

import { useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  FileUp,
  MessageSquare,
  Plus,
} from "lucide-react";
import {
  commandSchema,
  formatMoney,
  parseMajorUnits,
  safeEvidenceUrl,
  textValue,
  type FinanceCommand,
  type FinanceSnapshot,
  type Scope,
} from "@/lib/contracts";

type RecordValue = Record<string, unknown>;
type Mode = "message" | "manual" | "upload";

export function manualEntryPayload(
  description: string,
  amount: string,
  currency: string,
  direction: string,
) {
  if (!description.trim() || description.trim().length > 4000)
    throw new Error(
      "Describe the expense or expected income in 4,000 characters or fewer.",
    );
  if (direction !== "payable" && direction !== "receivable")
    throw new Error("Choose whether the event owes or expects this money.");
  return {
    source: "manual",
    description: description.trim(),
    amount_minor: parseMajorUnits(amount, currency),
    currency,
    direction,
  };
}

export function budgetProposalArguments(input: {
  line?: RecordValue;
  name: string;
  amount: string;
  currency: string;
  rationale: string;
  idempotencyKey: string;
}) {
  if (!input.rationale.trim() || input.rationale.trim().length > 2000)
    throw new Error("Explain the allocation in 2,000 characters or fewer.");
  const common = {
    allocated_minor: parseMajorUnits(input.amount, input.currency),
    rationale: input.rationale.trim(),
    idempotency_key: input.idempotencyKey,
  };
  if (input.line) {
    if (
      typeof input.line.id !== "string" ||
      typeof input.line.version !== "number" ||
      !Number.isSafeInteger(input.line.version) ||
      input.line.version < 1
    )
      throw new Error(
        "Refresh the budget before proposing a change to this category.",
      );
    return {
      ...common,
      budget_line_id: input.line.id,
      expected_version: input.line.version,
    };
  }
  if (!input.name.trim() || input.name.trim().length > 120)
    throw new Error("Name the budget category in 120 characters or fewer.");
  return { ...common, new_name: input.name.trim() };
}

async function jsonRequest(url: string, value: unknown) {
  const response = await fetch(url, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(value),
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(result.error ?? "The request was not accepted. Try again.");
  return result;
}

export function Workbench({
  scope,
  currency,
  cases,
  canEdit,
  busy,
  onCommand,
  onRefresh,
}: {
  scope: Scope;
  currency: string;
  cases: FinanceSnapshot["cases"];
  canEdit: boolean;
  busy: boolean;
  onCommand: (type: FinanceCommand, payload: RecordValue) => Promise<boolean>;
  onRefresh: () => Promise<void>;
}) {
  const [mode, setMode] = useState<Mode>("message");
  const [message, setMessage] = useState("");
  const [caseId, setCaseId] = useState("");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [direction, setDirection] = useState("payable");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [retry, setRetry] = useState<RecordValue | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const locked = !canEdit || busy || uploading;

  async function upload() {
    if (!file || locked) return;
    setFailure(null);
    setNotice(null);
    if (file.size < 1 || file.size > 3 * 1024 * 1024) {
      setFailure("Choose a nonempty document up to 3 MiB.");
      return;
    }
    setUploading(true);
    try {
      const data = new FormData();
      data.set("organization_id", scope.organization_id);
      data.set("run_id", scope.run_id);
      data.set("file", file);
      const response = await fetch("/api/finance/upload", {
        method: "POST",
        body: data,
        cache: "no-store",
      });
      const result = await response.json();
      if (!response.ok) {
        const parsed = commandSchema.safeParse(result.retry_command);
        if (
          parsed.success &&
          parsed.data.organization_id === scope.organization_id &&
          parsed.data.run_id === scope.run_id &&
          parsed.data.command_type === "intake" &&
          parsed.data.payload.source === "upload"
        )
          setRetry(parsed.data);
        throw new Error(
          result.error ??
            "The upload was not accepted. Check the file and try again.",
        );
      }
      setRetry(null);
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      setNotice(
        `Document review queued. Job ${textValue(result.job_id)}. Extraction and review will appear in activity.`,
      );
      await onRefresh();
    } catch (error) {
      setFailure(
        error instanceof Error
          ? error.message
          : "The upload result is unknown. Check activity before uploading again.",
      );
    } finally {
      setUploading(false);
    }
  }

  async function retryReview() {
    if (!retry || locked) return;
    setUploading(true);
    setFailure(null);
    try {
      const result = await jsonRequest("/api/finance/commands", retry);
      setRetry(null);
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      setNotice(
        `Stored document review queued. Job ${textValue(result.job_id)}.`,
      );
      await onRefresh();
    } catch (error) {
      setFailure(
        error instanceof Error
          ? error.message
          : "Review was not queued. Retry when the service is available.",
      );
    } finally {
      setUploading(false);
    }
  }

  return (
    <section className="finance-workbench" aria-labelledby="workbench-title">
      <div className="section-heading">
        <h2 id="workbench-title">Work with Finney</h2>
      </div>
      <div className="workbench-modes" aria-label="Choose a finance task">
        {(
          [
            ["message", "Ask Finney", MessageSquare],
            ["manual", "Add a record", Plus],
            ["upload", "Upload a document", FileUp],
          ] as const
        ).map(([id, label, Icon]) => (
          <button
            key={id}
            type="button"
            aria-pressed={mode === id}
            disabled={uploading}
            onClick={() => {
              setMode(id);
              setFailure(null);
              setNotice(null);
            }}
          >
            <Icon size={15} aria-hidden="true" />
            {label}
          </button>
        ))}
      </div>
      {!canEdit && (
        <p className="section-description">
          An active director or finance team member can add evidence and request
          work.
        </p>
      )}
      {mode === "message" && (
        <form
          className="workbench-form"
          onSubmit={async (event) => {
            event.preventDefault();
            if (locked || !message.trim()) return;
            setFailure(null);
            if (
              await onCommand("director_message", {
                message: message.trim(),
                ...(caseId ? { case_id: caseId } : {}),
              })
            )
              setMessage("");
          }}
        >
          <label htmlFor="finney-message">What should Finney work on?</label>
          <textarea
            id="finney-message"
            rows={3}
            maxLength={4000}
            required
            disabled={locked}
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="Review the catering quote against our food budget and show the missing evidence."
          />
          <div className="workbench-fields">
            <label htmlFor="finney-case">
              Related case
              <select
                id="finney-case"
                value={caseId}
                disabled={locked}
                onChange={(event) => setCaseId(event.target.value)}
              >
                <option value="">General event request</option>
                {cases.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.title}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="primary"
              type="submit"
              disabled={locked || !message.trim()}
            >
              Queue request <ArrowRight size={15} />
            </button>
          </div>
          <p>
            Finney reviews your event’s records. Payment proposals still follow
            the event’s human approval policy.
          </p>
        </form>
      )}
      {mode === "manual" && (
        <form
          className="workbench-form"
          onSubmit={async (event) => {
            event.preventDefault();
            if (locked) return;
            setFailure(null);
            try {
              const payload = manualEntryPayload(
                description,
                amount,
                currency,
                direction,
              );
              if (await onCommand("intake", payload)) {
                setDescription("");
                setAmount("");
              }
            } catch (error) {
              setFailure(
                error instanceof Error
                  ? error.message
                  : "Check the entry and try again.",
              );
            }
          }}
        >
          <label htmlFor="manual-description">Expense or expected income</label>
          <textarea
            id="manual-description"
            rows={2}
            required
            maxLength={4000}
            disabled={locked}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Catering quote for Saturday lunch, awaiting the final invoice."
          />
          <div className="workbench-fields">
            <label htmlFor="manual-amount">
              Amount ({currency})
              <input
                id="manual-amount"
                inputMode="decimal"
                required
                maxLength={40}
                disabled={locked}
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                placeholder="0.00"
              />
            </label>
            <label htmlFor="manual-direction">
              Direction
              <select
                id="manual-direction"
                value={direction}
                disabled={locked}
                onChange={(event) => setDirection(event.target.value)}
              >
                <option value="payable">Event owes money</option>
                <option value="receivable">Event expects money</option>
              </select>
            </label>
            <button
              className="primary"
              type="submit"
              disabled={locked || !description.trim() || !amount.trim()}
            >
              Queue record review <ArrowRight size={15} />
            </button>
          </div>
          <p>
            This records reported evidence for review. It does not establish
            cash or confirm a payment.
          </p>
        </form>
      )}
      {mode === "upload" && (
        <form
          className="workbench-form"
          onSubmit={(event) => {
            event.preventDefault();
            void upload();
          }}
        >
          <label htmlFor="finance-document">
            Invoice, agreement or receipt
          </label>
          <input
            id="finance-document"
            ref={fileInput}
            type="file"
            disabled={locked || Boolean(retry)}
            accept=".pdf,.txt,.md,.csv,.png,.jpg,.jpeg,.webp,.gif"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setFailure(null);
              setNotice(null);
            }}
          />
          <p>
            PDF, text, CSV or receipt image, up to 3 MiB. Scanned PDFs support
            up to four pages per review. Model-extracted text needs
            verification.
          </p>
          {retry && (
            <p>
              The original document is stored. Retry review without uploading
              another copy.
            </p>
          )}
          {retry ? (
            <button
              type="button"
              disabled={locked}
              onClick={() => void retryReview()}
            >
              {uploading ? "Queuing review…" : "Retry document review"}
            </button>
          ) : (
            <button
              className="primary"
              type="submit"
              disabled={locked || !file}
            >
              {uploading ? "Uploading…" : "Upload & queue review"}
              <FileUp size={15} />
            </button>
          )}
        </form>
      )}
      {failure && (
        <p className="workbench-error" role="alert">
          {failure}
        </p>
      )}
      {notice && (
        <p className="workbench-notice" role="status">
          {notice}
        </p>
      )}
    </section>
  );
}

export function BudgetWorkbench({
  scope,
  currency,
  budget,
  canEdit,
  canDecide,
  onRefresh,
}: {
  scope: Scope;
  currency: string;
  budget: FinanceSnapshot["budget"];
  canEdit: boolean;
  canDecide: boolean;
  onRefresh: () => Promise<void>;
}) {
  const [showForm, setShowForm] = useState(false);
  const [selected, setSelected] = useState("");
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const keys = useRef(new Map<string, string>());
  async function decide(id: string, decision: "approve" | "reject") {
    if (!canDecide || busy) return;
    setBusy(true);
    setFailure(null);
    setNotice(null);
    try {
      await jsonRequest("/api/finance/budget", {
        ...scope,
        operation: "decide",
        decision_id: id,
        decision,
      });
      setNotice(
        `Budget ${decision === "approve" ? "allocation approved" : "proposal rejected"}.`,
      );
      await onRefresh();
    } catch (error) {
      setFailure(
        error instanceof Error
          ? error.message
          : "The decision was not saved. Refresh the budget and try again.",
      );
      await onRefresh();
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="budget-workbench" aria-labelledby="budget-title">
      <div className="section-heading">
        <h2 id="budget-title">Budget allocations</h2>
        <button
          type="button"
          className="text-button"
          disabled={!canEdit || busy}
          onClick={() => setShowForm(!showForm)}
        >
          {showForm ? "Close proposal" : "Propose allocation"}
          <Plus size={14} />
        </button>
      </div>
      {budget.lines.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Category</th>
                <th>Allocated</th>
                <th>Committed</th>
                <th>Remaining</th>
              </tr>
            </thead>
            <tbody>
              {budget.lines.map((line) => (
                <tr key={textValue(line.id)}>
                  <td>{textValue(line.name)}</td>
                  {[
                    "allocated_minor",
                    "committed_minor",
                    "remaining_minor",
                  ].map((field) => (
                    <td key={field}>
                      {formatMoney(
                        typeof line[field] === "string"
                          ? (line[field] as string)
                          : null,
                        textValue(line.currency, currency),
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="section-description">
          No budget categories have been approved. Propose an allocation to plan
          event spending.
        </p>
      )}
      <p className="budget-basis">
        Allocations plan spending; recorded cash remains separate.
      </p>
      {showForm && (
        <form
          className="workbench-form budget-form"
          onSubmit={async (event) => {
            event.preventDefault();
            if (!canEdit || busy) return;
            setFailure(null);
            setNotice(null);
            try {
              const input = {
                line: selected
                  ? budget.lines.find((line) => line.id === selected)
                  : undefined,
                name,
                amount,
                currency,
                rationale,
                idempotencyKey: "pending",
              };
              if (selected && !input.line)
                throw new Error(
                  "Refresh the budget before changing this category.",
                );
              const signature = JSON.stringify(input);
              const key = keys.current.get(signature) ?? crypto.randomUUID();
              keys.current.set(signature, key);
              const args = budgetProposalArguments({
                ...input,
                idempotencyKey: key,
              });
              setBusy(true);
              await jsonRequest("/api/finance/budget", {
                ...scope,
                operation: "propose",
                arguments: args,
              });
              keys.current.delete(signature);
              setNotice(
                "Budget proposal saved. A director decision is required before the allocation changes.",
              );
              setShowForm(false);
              setName("");
              setAmount("");
              setRationale("");
              await onRefresh();
            } catch (error) {
              setFailure(
                error instanceof Error
                  ? error.message
                  : "The proposal was not saved. Check the fields and try again.",
              );
            } finally {
              setBusy(false);
            }
          }}
        >
          <div className="workbench-fields">
            <label htmlFor="budget-category">
              Category
              <select
                id="budget-category"
                disabled={busy}
                value={selected}
                onChange={(event) => setSelected(event.target.value)}
              >
                <option value="">New category</option>
                {budget.lines.map((line) => (
                  <option value={textValue(line.id)} key={textValue(line.id)}>
                    {textValue(line.name)}
                  </option>
                ))}
              </select>
            </label>
            {!selected && (
              <label htmlFor="budget-name">
                New category name
                <input
                  id="budget-name"
                  required
                  maxLength={120}
                  disabled={busy}
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              </label>
            )}
            <label htmlFor="budget-amount">
              Total allocation ({currency})
              <input
                id="budget-amount"
                inputMode="decimal"
                required
                maxLength={40}
                disabled={busy}
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                placeholder="0.00"
              />
            </label>
          </div>
          <label htmlFor="budget-rationale">Reason for this allocation</label>
          <textarea
            id="budget-rationale"
            rows={2}
            required
            maxLength={2000}
            disabled={busy}
            value={rationale}
            onChange={(event) => setRationale(event.target.value)}
          />
          <button type="submit" className="primary" disabled={busy || !canEdit}>
            {busy ? "Saving proposal…" : "Save budget proposal"}
            <ArrowRight size={15} />
          </button>
        </form>
      )}
      {budget.decisions.length > 0 && (
        <div className="budget-decisions">
          <h3>Allocation decisions</h3>
          {budget.decisions.map((decision) => (
            <article key={textValue(decision.id)}>
              <div>
                <strong>
                  {textValue(decision.name)} ·{" "}
                  {formatMoney(
                    typeof decision.allocated_minor === "string"
                      ? decision.allocated_minor
                      : null,
                    textValue(decision.currency, currency),
                  )}
                </strong>
                <p>{textValue(decision.rationale)}</p>
                <span>{textValue(decision.status).replaceAll("_", " ")}</span>
              </div>
              {decision.status === "pending" && canDecide && (
                <div className="budget-decision-actions">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void decide(textValue(decision.id), "reject")
                    }
                  >
                    Reject allocation
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void decide(textValue(decision.id), "approve")
                    }
                  >
                    Approve allocation
                  </button>
                </div>
              )}
              {decision.status === "pending" && !canDecide && (
                <p className="muted">Awaiting a director decision</p>
              )}
            </article>
          ))}
        </div>
      )}
      {failure && (
        <p className="workbench-error" role="alert">
          {failure}
        </p>
      )}
      {notice && (
        <p className="workbench-notice" role="status">
          {notice}
        </p>
      )}
    </section>
  );
}

export function ArtifactDownload({
  scope,
  path,
  label = "Download original document",
}: {
  scope: Scope;
  path: string;
  label?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  return (
    <div className="source-download">
      <button
        disabled={busy}
        onClick={async () => {
          setFailure(null);
          setBusy(true);
          try {
            if (!path.startsWith(`${scope.organization_id}/${scope.run_id}/`))
              throw new Error("The document does not belong to this event.");
            const response = await fetch(
              `/api/finance/artifact?${new URLSearchParams({ ...scope, path })}`,
              { cache: "no-store" },
            );
            const result = await response.json();
            if (!response.ok)
              throw new Error(
                result.error ?? "The document is unavailable to this account.",
              );
            const url = safeEvidenceUrl(result.download_url);
            if (!url)
              throw new Error(
                "The download link could not be verified. Try again.",
              );
            const anchor = document.createElement("a");
            anchor.href = url;
            anchor.rel = "noreferrer";
            anchor.download = "";
            anchor.click();
          } catch (error) {
            setFailure(
              error instanceof Error
                ? error.message
                : "The document could not be downloaded.",
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        <ArrowDownToLine size={13} />
        {busy ? "Preparing download…" : label}
      </button>
      {failure && <p role="alert">{failure}</p>}
    </div>
  );
}

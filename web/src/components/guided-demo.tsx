"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, Play, X } from "lucide-react";
import { formatMoney, type FinanceSnapshot } from "@/lib/contracts";

export type DemoDestination =
  "cases" | "overview" | "approvals" | "reports" | "learning";
export function guidedAVDecision(snapshot: FinanceSnapshot) {
  const line = snapshot.budget.lines.find(
    (row) => String(row.name).trim().toUpperCase() === "AV",
  );
  return snapshot.budget.decisions
    .filter(
      (row) =>
        ((line?.id && row.budget_line_id === line.id) ||
          String(row.name ?? row.new_name)
            .trim()
            .toUpperCase() === "AV") &&
        String(row.allocated_minor) === "100000" &&
        (!row.currency || row.currency === "USD"),
    )
    .sort(
      (left, right) =>
        (Date.parse(String(right.created_at)) || 0) -
        (Date.parse(String(left.created_at)) || 0),
    )[0];
}

export function GuidedDemo({
  snapshot,
  compact,
  onNavigate,
  onPrompt,
  busy,
  onRetry,
}: {
  snapshot: FinanceSnapshot;
  compact: boolean;
  busy: boolean;
  onRetry: () => void;
  onPrompt: (caseId: string, prompt: string) => Promise<boolean>;
  onNavigate: (
    destination: DemoDestination,
    caseId?: string,
    prompt?: string,
  ) => void;
}) {
  const scenario = snapshot.run.scenario;
  const storageKey = `finney-walkthrough:${snapshot.organization.id}:${snapshot.run.id}`;
  const [step, setStep] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) ?? "null");
      setStep(
        Number.isInteger(saved?.step)
          ? Math.min(Math.max(saved.step, 0), 3)
          : 0,
      );
      setDismissed(saved?.dismissed === true);
    } catch {
      /* Storage can be unavailable; the walkthrough still works. */
    }
    setLoaded(true);
  }, [storageKey]);
  useEffect(() => {
    if (loaded)
      try {
        localStorage.setItem(storageKey, JSON.stringify({ step, dismissed }));
      } catch {
        /* Optional preference only. */
      }
  }, [storageKey, loaded, step, dismissed]);
  if (!scenario || !loaded) return null;
  const scenarioStep = scenario.steps?.find(
    (item) => item.id === ["catch", "decide", "report"][step],
  );
  const focus = snapshot.cases.find((row) => row.id === scenarioStep?.case_id);
  const budgetDecision = guidedAVDecision(snapshot);
  const pendingBudget = budgetDecision?.status === "pending";
  const rejectedBudget = budgetDecision?.status === "rejected";
  const approvedBudget = budgetDecision?.status === "approved";
  // The public job projection intentionally excludes arbitrary payloads. The
  // guided run has one worker; suppress duplicate guided prompts while any
  // director request in this run is queued/running. Other UI remains available.
  const working = snapshot.jobs.some(
    (row) =>
      row.command_type === "director_message" &&
      ["queued", "running"].includes(String(row.status)),
  );
  const steps = [
    {
      title: "A bill changed. What do we actually owe?",
      body: "Compare both invoice versions with the existing commitment.",
      action: "Check the revised invoice",
    },
    {
      title: "Your decision changes the plan.",
      body: approvedBudget
        ? "The AV budget increase was approved. The allocation is now part of the event plan; approval is not payment."
        : pendingBudget
          ? "Finney has prepared a budget proposal. The decision is yours."
          : rejectedBudget
            ? "The proposal was declined. Ask Finney for a plan that respects your decision."
            : "Ask Finney to propose an AV budget increase. You can approve or decline the actual proposal.",
      action: approvedBudget
        ? "View the approved budget"
        : pendingBudget
          ? "Decide the budget proposal"
          : rejectedBudget
            ? "Ask for another plan"
            : "Prepare a budget proposal",
    },
    {
      title: "A receipt is not always another bill.",
      body: "Mira paid with a personal card and submitted the receipt twice. Ask Finney to work out the remaining obligation and update the event position.",
      action: "Review Mira’s purchase",
    },
    {
      title: "Make improvement prove itself.",
      body: "See whether this practice event has produced learning evidence. A candidate stays inactive until it passes the protected tests.",
      action: "Inspect the learning evidence",
    },
  ];
  const current = steps[step];
  const ready = scenario.status === "ready";
  const preparationFailed =
    !ready &&
    ["failed", "blocked", "cancelled"].includes(scenario.seed_status ?? "");
  const runAction = async () => {
    if (step === 3) {
      onNavigate("learning");
      return;
    }
    if (step === 1 && (pendingBudget || approvedBudget)) {
      onNavigate("overview");
      return;
    }
    if (!focus || !scenarioStep?.prompt || !ready) return;
    const prompt =
      step === 1 && rejectedBudget
        ? "I declined the budget increase. Keep the existing allocation unchanged, explain our options, and do not treat my refusal as permission to pay."
        : scenarioStep.prompt;
    if (await onPrompt(focus.id, prompt)) onNavigate("cases", focus.id);
  };
  if (dismissed)
    return (
      <div className="walkthrough-resume">
        <span>Practice event · synthetic records</span>
        <button className="text-button" onClick={() => setDismissed(false)}>
          <Play size={15} /> Resume walkthrough
        </button>
      </div>
    );
  return (
    <section
      className={`guided-demo ${compact ? "guided-demo-compact" : ""}`}
      aria-label="Finance walkthrough"
    >
      <header className="guided-demo-heading">
        <span>Practice event · synthetic records</span>
        <button
          className="text-button"
          onClick={() => setDismissed(true)}
          aria-label="Skip walkthrough"
        >
          <X size={18} /> Skip walkthrough
        </button>
      </header>
      {!compact && (
        <div className="demo-situation">
          <img src="/brand/finney.svg" alt="" />
          <div>
            <h2>{scenario.title}</h2>
            <p>{scenario.brief}</p>
          </div>
        </div>
      )}
      {!compact && (
        <dl className="demo-position">
          <div>
            <dt>Recorded cash</dt>
            <dd>
              {formatMoney(snapshot.position.cash_minor, snapshot.run.currency)}
            </dd>
          </div>
          <div>
            <dt>Money owed</dt>
            <dd>
              {formatMoney(
                snapshot.position.committed_minor,
                snapshot.run.currency,
              )}
            </dd>
          </div>
          <div>
            <dt>Sponsorship pending</dt>
            <dd>
              {formatMoney(
                snapshot.position.receivable_minor,
                snapshot.run.currency,
              )}
            </dd>
          </div>
        </dl>
      )}
      {preparationFailed && (
        <div className="walkthrough-preparation-error" role="alert">
          <p>
            The practice documents could not be prepared. Your existing records
            are safe.
          </p>
          {scenario.seed_retry_available ? (
            <button disabled={busy} onClick={onRetry}>
              Retry preparation
            </button>
          ) : (
            <p>
              Preparation needs attention. Ask the event owner to inspect the
              failed intake.
            </p>
          )}
        </div>
      )}
      <div className="walkthrough-step" key={step}>
        <div>
          <p className="walkthrough-position">
            Walkthrough · {step + 1} of {steps.length}
          </p>
          <h3>{current.title}</h3>
          <p>{current.body}</p>
        </div>
        <button
          className="primary"
          disabled={busy || (step < 3 && (!ready || working || !focus))}
          onClick={() => void runAction()}
        >
          {!ready
            ? "Preparing documents…"
            : working
              ? "Finney is working…"
              : current.action}
          <ArrowRight size={16} />
        </button>
      </div>
      {step < 3 && ready && (
        <div className="walkthrough-outcome-links">
          {focus && (
            <button
              className="text-button"
              onClick={() => onNavigate("cases", focus.id)}
            >
              Open the case <ArrowRight size={15} />
            </button>
          )}
          {step === 1 && (
            <button
              className="text-button"
              onClick={() => onNavigate("overview")}
            >
              Budget decisions <ArrowRight size={15} />
            </button>
          )}
          {step === 2 && (
            <button
              className="text-button"
              onClick={() => onNavigate("reports")}
            >
              Generate an event report <ArrowRight size={15} />
            </button>
          )}
        </div>
      )}
      <footer className="walkthrough-controls">
        <button
          className="text-button"
          disabled={step === 0}
          onClick={() => setStep(step - 1)}
        >
          <ArrowLeft size={15} />
          Back
        </button>
        <div aria-label="Walkthrough progress">
          {steps.map((item, index) => (
            <button
              key={item.title}
              aria-label={`Step ${index + 1}: ${item.title}`}
              aria-current={index === step ? "step" : undefined}
              onClick={() => setStep(index)}
            >
              {index + 1}
            </button>
          ))}
        </div>
        <button
          className="text-button"
          onClick={() => (step === 3 ? setDismissed(true) : setStep(step + 1))}
        >
          {step === 3 ? "Explore on my own" : "Next"}
          <ArrowRight size={15} />
        </button>
      </footer>
    </section>
  );
}

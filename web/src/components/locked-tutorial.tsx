"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { FinanceSnapshot } from "@/lib/contracts";

export const LOCKED_TUTORIAL_VERSION = "alert-review-v1";
export type TutorialCommand = {
  jobId: string;
  type: string;
  caseId: string | null;
};
type Phase =
  "intro" | "alert" | "review" | "waiting" | "budget" | "done" | "dismissed";
type Progress = {
  phase: Phase;
  caseId: string | null;
  command: TutorialCommand | null;
};
type Receipt = { key: string; progress: Progress };
type Rect = {
  top: number;
  left: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
};
const initial = (): Progress => ({
  phase: "intro",
  caseId: null,
  command: null,
});
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

export function tutorialStorageKey(snapshot: FinanceSnapshot): string {
  return `finney-locked-tutorial:${LOCKED_TUTORIAL_VERSION}:${snapshot.organization.id}:${snapshot.run.id}`;
}

// A completed worker job alone is not a financial result. Require the stored,
// guarded persistence marker for precisely the accepted job and selected case.
export function tutorialHasPersistedResult(
  snapshot: FinanceSnapshot,
  command: TutorialCommand,
): boolean {
  const job = snapshot.jobs.find((item) => item.id === command.jobId);
  if (
    !job ||
    job.status !== "completed" ||
    job.command_type !== command.type ||
    (job.case_id ?? record(job.payload).case_id) !== command.caseId
  )
    return false;
  const item = snapshot.cases.find((item) => item.id === command.caseId);
  if (!item) return false;
  const finding = record(item.data.finding);
  const provenance = record(finding.provenance);
  return (
    command.type === "review_case" &&
    finding.kind === "prepared_agent_review" &&
    finding.verification === "unverified_model_recommendation" &&
    typeof finding.decision === "string" &&
    /^[a-z][a-z0-9_]{0,79}$/.test(finding.decision) &&
    typeof finding.explanation === "string" &&
    Boolean(finding.explanation.trim()) &&
    provenance.job_id === command.jobId &&
    typeof provenance.actor_trace_id === "string" &&
    Boolean(provenance.actor_trace_id)
  );
}

function readProgress(key: string): Progress {
  try {
    const value = record(JSON.parse(localStorage.getItem(key) ?? "null"));
    const phase = value.phase;
    if (
      ![
        "intro",
        "alert",
        "review",
        "waiting",
        "budget",
        "done",
        "dismissed",
      ].includes(String(phase))
    )
      return initial();
    const command = record(value.command);
    const accepted =
      typeof command.jobId === "string" &&
      command.jobId.length > 0 &&
      command.type === "review_case" &&
      typeof command.caseId === "string"
        ? (command as TutorialCommand)
        : null;
    const caseId = typeof value.caseId === "string" ? value.caseId : null;
    if (
      ["waiting", "budget", "done"].includes(String(phase)) &&
      (!accepted || accepted.caseId !== caseId)
    )
      return initial();
    if (phase === "review" && !caseId) return initial();
    return { phase: phase as Phase, caseId, command: accepted };
  } catch {
    return initial();
  }
}

function visibleTarget(name: string | null): HTMLElement | null {
  if (!name) return null;
  return (
    Array.from(
      document.querySelectorAll<HTMLElement>(`[data-tutorial="${name}"]`),
    ).find(
      (element) =>
        element.getClientRects().length > 0 &&
        getComputedStyle(element).visibility !== "hidden",
    ) ?? null
  );
}

export function LockedTutorial({
  snapshot,
  selectedCaseId,
  tab,
  lastCommand,
  onNavigate,
}: {
  snapshot: FinanceSnapshot | null;
  selectedCaseId: string | null;
  tab: string;
  lastCommand: TutorialCommand | null;
  onNavigate?: (destination: "cases" | "overview", caseId?: string) => void;
}) {
  const key = snapshot ? tutorialStorageKey(snapshot) : "";
  const eligible = Boolean(
    snapshot?.run.scenario?.synthetic && snapshot.run.status === "active",
  );
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const progress = receipt?.key === key ? receipt.progress : null;
  const [portal, setPortal] = useState<HTMLDivElement | null>(null);
  const [target, setTarget] = useState<HTMLElement | null>(null);
  const [rect, setRect] = useState<Rect | null>(null);
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const [interaction, setInteraction] = useState(0);
  const descriptionId = useId();
  const current = useRef({
    snapshot,
    selectedCaseId,
    tab,
    lastCommand,
    progress,
  });
  current.current = { snapshot, selectedCaseId, tab, lastCommand, progress };
  const opening = useRef(false);
  const reviewing = useRef<{ caseId: string; excluded: Set<string> } | null>(
    null,
  );
  const viewingBudget = useRef(false);
  const restoreView = useRef(false);

  function update(next: Progress) {
    setReceipt({ key, progress: next });
    try {
      localStorage.setItem(key, JSON.stringify(next));
    } catch {
      /* Optional local preference. */
    }
  }
  const updateRef = useRef(update);
  updateRef.current = update;
  const active = Boolean(
    eligible && progress && progress.phase !== "dismissed",
  );
  const job = snapshot?.jobs.find((job) => job.id === progress?.command?.jobId);
  const failed =
    progress?.phase === "waiting" &&
    ["failed", "blocked", "cancelled"].includes(String(job?.status));
  const validResult = Boolean(
    snapshot &&
    progress?.command &&
    tutorialHasPersistedResult(snapshot, progress.command),
  );
  const targetName =
    progress?.phase === "alert"
      ? "open-alert"
      : progress?.phase === "review" || failed
        ? "review-case"
        : progress?.phase === "budget" && validResult
          ? "view-budget"
          : progress?.phase === "waiting"
            ? "finney-working"
            : null;
  const interactiveTarget = targetName === "finney-working" ? null : target;
  const showCoach = !(
    progress?.phase === "waiting" &&
    !failed &&
    target?.matches('[data-tutorial="finney-working"]')
  );

  useEffect(() => {
    if (!key || !eligible) {
      setReceipt(null);
      return;
    }
    opening.current = false;
    reviewing.current = null;
    viewingBudget.current = false;
    const saved = readProgress(key);
    restoreView.current = ["review", "waiting", "budget"].includes(saved.phase);
    setReceipt({ key, progress: saved });
  }, [key, eligible]);

  useEffect(() => {
    const node = document.createElement("div");
    node.dataset.lockedTutorialPortal = "";
    document.body.append(node);
    setPortal(node);
    return () => node.remove();
  }, []);

  useEffect(() => {
    if (!active || !progress || !snapshot) return;
    if (
      progress.phase === "alert" &&
      opening.current &&
      tab === "cases" &&
      selectedCaseId
    ) {
      opening.current = false;
      updateRef.current({
        phase: "review",
        caseId: selectedCaseId,
        command: null,
      });
    }
    const attempt = reviewing.current;
    if (
      attempt &&
      lastCommand?.type === "review_case" &&
      lastCommand.caseId === attempt.caseId &&
      !attempt.excluded.has(lastCommand.jobId)
    ) {
      reviewing.current = null;
      updateRef.current({
        phase: "waiting",
        caseId: attempt.caseId,
        command: { ...lastCommand },
      });
    }
    if (progress.phase === "waiting" && validResult) {
      updateRef.current({ ...progress, phase: "budget" });
    }
    if (
      progress.phase === "budget" &&
      viewingBudget.current &&
      tab === "overview" &&
      validResult
    ) {
      viewingBudget.current = false;
      updateRef.current({ ...progress, phase: "done" });
    }
  }, [
    active,
    progress,
    snapshot,
    selectedCaseId,
    tab,
    lastCommand,
    validResult,
    interaction,
  ]);

  // A resumed review may be on another tab. Navigation only restores the saved
  // view; it never queues work or invents completion.
  useEffect(() => {
    if (active && progress?.caseId && restoreView.current) {
      restoreView.current = false;
      if (tab !== "cases" || selectedCaseId !== progress.caseId)
        onNavigate?.("cases", progress.caseId);
    }
  }, [
    active,
    key,
    progress?.phase,
    progress?.caseId,
    onNavigate,
    tab,
    selectedCaseId,
  ]);

  useEffect(() => {
    if (!active || !portal) {
      setTarget(null);
      setRect(null);
      return;
    }
    let frame = 0;
    let observed: HTMLElement | null = null;
    const resize = new ResizeObserver(schedule);
    function measure() {
      frame = 0;
      const next = visibleTarget(targetName);
      if (next !== observed) {
        if (observed) resize.unobserve(observed);
        observed = next;
        if (next) resize.observe(next);
      }
      setTarget((old) => (old === next ? old : next));
      const bounds = next?.getBoundingClientRect();
      setRect(
        bounds
          ? {
              top: bounds.top,
              left: bounds.left,
              right: bounds.right,
              bottom: bounds.bottom,
              width: bounds.width,
              height: bounds.height,
            }
          : null,
      );
      setViewport({ width: innerWidth, height: innerHeight });
    }
    function schedule() {
      if (!frame) frame = requestAnimationFrame(measure);
    }
    const mutations = new MutationObserver((entries) => {
      if (entries.some((entry) => !portal.contains(entry.target))) schedule();
    });
    mutations.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: [
        "disabled",
        "hidden",
        "style",
        "class",
        "data-tutorial",
      ],
    });
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, true);
    window.visualViewport?.addEventListener("resize", schedule);
    measure();
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      mutations.disconnect();
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule, true);
      window.visualViewport?.removeEventListener("resize", schedule);
    };
  }, [active, targetName, portal]);

  useEffect(() => {
    if (!active) return;
    const previous = document.activeElement;
    return () => {
      queueMicrotask(() => {
        if (
          previous instanceof HTMLElement &&
          previous.isConnected &&
          !previous.closest("[inert]")
        )
          previous.focus({ preventScroll: true });
      });
    };
  }, [active]);

  // Save the original attributes on each blocked branch. Never clear an inert
  // state owned by another modal or leave ours behind after Skip/unmount.
  useEffect(() => {
    if (!active || !portal) return;
    const saved = new Map<HTMLElement, string | null>();
    const isolate = (parent: HTMLElement) => {
      for (const child of Array.from(parent.children)) {
        if (!(child instanceof HTMLElement)) continue;
        if (child === portal || child === target) continue;
        if (target && child.contains(target)) isolate(child);
        else {
          saved.set(child, child.getAttribute("inert"));
          child.inert = true;
        }
      }
    };
    isolate(document.body);
    const observer = new MutationObserver(() => {
      for (const [element, value] of saved) {
        if (value === null) element.removeAttribute("inert");
        else element.setAttribute("inert", value);
      }
      saved.clear();
      isolate(document.body);
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      for (const [element, value] of saved) {
        if (value === null) element.removeAttribute("inert");
        else element.setAttribute("inert", value);
      }
    };
  }, [active, portal, target]);

  useEffect(() => {
    if (!active || !portal) return;
    const previousDescription =
      target?.getAttribute("aria-describedby") ?? null;
    if (target) {
      if (showCoach)
        target.setAttribute(
          "aria-describedby",
          [previousDescription, descriptionId].filter(Boolean).join(" "),
        );
      target.scrollIntoView({
        block: "center",
        inline: "nearest",
        behavior: "instant",
      });
    }
    (interactiveTarget && !interactiveTarget.matches(":disabled")
      ? interactiveTarget
      : (portal.querySelector<HTMLElement>("[data-tutorial-primary]") ??
        portal.querySelector<HTMLElement>("button"))
    )?.focus({ preventScroll: true });
    return () => {
      if (target) {
        if (previousDescription === null)
          target.removeAttribute("aria-describedby");
        else target.setAttribute("aria-describedby", previousDescription);
      }
    };
  }, [
    active,
    portal,
    target,
    interactiveTarget,
    descriptionId,
    progress?.phase,
    showCoach,
  ]);

  useEffect(() => {
    if (!active || !portal) return;
    const allowed = (node: EventTarget | null) =>
      node instanceof Node &&
      (portal.contains(node) || Boolean(interactiveTarget?.contains(node)));
    const stop = (event: Event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
    };
    const skip = () => {
      const latest = current.current.progress;
      if (latest) updateRef.current({ ...latest, phase: "dismissed" });
    };
    const pointer = (event: Event) => {
      if (!allowed(event.target)) {
        stop(event);
        return;
      }
      if (
        event.type !== "click" ||
        !target?.contains(event.target as Node) ||
        target.matches(":disabled")
      )
        return;
      const latest = current.current;
      if (targetName === "open-alert") {
        opening.current = true;
        setInteraction((value) => value + 1);
      }
      if (
        targetName === "review-case" &&
        latest.selectedCaseId === latest.progress?.caseId
      ) {
        reviewing.current = {
          caseId: latest.selectedCaseId!,
          excluded: new Set([
            ...(latest.snapshot?.jobs.map((item) => String(item.id)) ?? []),
            ...(latest.lastCommand ? [latest.lastCommand.jobId] : []),
          ]),
        };
      }
      if (targetName === "view-budget") viewingBudget.current = true;
    };
    const focusables = () => [
      ...(interactiveTarget &&
      !interactiveTarget.matches(":disabled") &&
      !interactiveTarget.closest("[inert]")
        ? [interactiveTarget]
        : []),
      ...Array.from(
        portal.querySelectorAll<HTMLElement>(
          "button:not(:disabled),a[href],[tabindex='0']",
        ),
      ),
    ];
    const focus = (event: FocusEvent) => {
      if (!allowed(event.target)) {
        event.stopImmediatePropagation();
        focusables()[0]?.focus({ preventScroll: true });
      }
    };
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape" && event.type === "keydown") {
        stop(event);
        skip();
        return;
      }
      // Keep browser navigation/reload, window controls, zoom and copying usable.
      // Their keystrokes must not reach application shortcuts underneath us.
      if (
        event.ctrlKey ||
        event.metaKey ||
        ["F5", "F6", "F11", "F12"].includes(event.key) ||
        (event.altKey && ["ArrowLeft", "ArrowRight"].includes(event.key))
      ) {
        event.stopImmediatePropagation();
        return;
      }
      if (event.key === "Tab") {
        stop(event);
        if (event.type !== "keydown") return;
        const options = focusables();
        const index = options.indexOf(document.activeElement as HTMLElement);
        options[
          (index + (event.shiftKey ? -1 : 1) + options.length) % options.length
        ]?.focus({ preventScroll: true });
        return;
      }
      if (
        !allowed(event.target) ||
        event.altKey ||
        !["Enter", " ", "Shift"].includes(event.key)
      )
        stop(event);
    };
    const events = [
      "pointerdown",
      "mousedown",
      "touchstart",
      "click",
      "dblclick",
      "contextmenu",
      "dragstart",
    ];
    events.forEach((name) =>
      window.addEventListener(name, pointer, { capture: true, passive: false }),
    );
    window.addEventListener("keydown", keyboard, true);
    window.addEventListener("keyup", keyboard, true);
    window.addEventListener("keypress", keyboard, true);
    window.addEventListener("focusin", focus, true);
    return () => {
      events.forEach((name) => window.removeEventListener(name, pointer, true));
      window.removeEventListener("keydown", keyboard, true);
      window.removeEventListener("keyup", keyboard, true);
      window.removeEventListener("keypress", keyboard, true);
      window.removeEventListener("focusin", focus, true);
    };
  }, [active, portal, target, interactiveTarget, targetName]);

  if (!active || !portal || !progress) return null;
  const intro = progress.phase === "intro";
  const done = progress.phase === "done";
  const message = intro
    ? "You’re organizing Hack Harbor. Five days to go. Finney has an update."
    : progress.phase === "alert"
      ? "Open Finney’s latest alert."
      : progress.phase === "review"
        ? "Ask Finney to review the case."
        : failed
          ? "The review didn’t finish. Review again, or skip the demo."
          : progress.phase === "waiting"
            ? job?.status === "completed"
              ? "Finishing up."
              : "Finney’s on it."
            : progress.phase === "budget"
              ? validResult
                ? "See where your event budget stands."
                : "Waiting for this review’s stored result."
              : "You’re ready.";
  const padding = 6;
  const hole =
    target && rect
      ? {
          top: Math.max(0, rect.top - padding),
          left: Math.max(0, rect.left - padding),
          right: Math.min(viewport.width, rect.right + padding),
          bottom: Math.min(viewport.height, rect.bottom + padding),
        }
      : null;
  const coachWidth = Math.min(360, Math.max(0, viewport.width - 32));
  const nearBottom = Boolean(hole && hole.top > viewport.height / 2);
  const coachStyle =
    intro || done
      ? undefined
      : hole
        ? {
            left: Math.max(
              16,
              Math.min(hole.left, viewport.width - coachWidth - 16),
            ),
            ...(nearBottom
              ? { bottom: viewport.height - hole.top + 16 }
              : { top: Math.max(76, hole.bottom + 16) }),
          }
        : { bottom: 24, left: Math.max(16, (viewport.width - coachWidth) / 2) };
  return createPortal(
    <div className="locked-tutorial" data-tutorial-phase={progress.phase}>
      <link rel="stylesheet" href="/brand/locked-tutorial.css" />
      {hole ? (
        <>
          <div
            className="locked-tutorial-shade"
            style={{ top: 0, left: 0, width: "100%", height: hole.top }}
          />
          <div
            className="locked-tutorial-shade"
            style={{
              top: hole.top,
              left: 0,
              width: hole.left,
              height: hole.bottom - hole.top,
            }}
          />
          <div
            className="locked-tutorial-shade"
            style={{
              top: hole.top,
              left: hole.right,
              right: 0,
              height: hole.bottom - hole.top,
            }}
          />
          <div
            className="locked-tutorial-shade"
            style={{ top: hole.bottom, left: 0, right: 0, bottom: 0 }}
          />
          <div
            className="locked-tutorial-outline"
            aria-hidden="true"
            style={{
              top: hole.top,
              left: hole.left,
              width: hole.right - hole.left,
              height: hole.bottom - hole.top,
            }}
          />
        </>
      ) : (
        <div className="locked-tutorial-shade locked-tutorial-full" />
      )}
      <button
        className="locked-tutorial-skip"
        onClick={() => update({ ...progress, phase: "dismissed" })}
      >
        Skip demo
      </button>
      {showCoach && (
        <section
          className={`locked-tutorial-coach${intro || done ? " locked-tutorial-centered" : ""}`}
          style={coachStyle}
          role={intro || done ? "dialog" : "region"}
          aria-modal={intro || done ? true : undefined}
          aria-label="Finney demo"
        >
          <p
            id={descriptionId}
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            {message}
          </p>
          {(intro || done) && (
            <button
              className="locked-tutorial-primary"
              data-tutorial-primary
              onClick={() =>
                update({ ...progress, phase: done ? "dismissed" : "alert" })
              }
            >
              {done ? "Done" : "Let’s go"}
            </button>
          )}
        </section>
      )}
    </div>,
    portal,
  );
}

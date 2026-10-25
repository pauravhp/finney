import type { FinanceSnapshot } from "@/lib/contracts";

export const PHOTO_BOOTH_SCENARIO_ID = "finney-photo-booth-v1";
export const PHOTO_BOOTH_OPENING_PROMPT =
  "The team thinks sponsorship covers the photo booth. Review the latest documents, resolve what you can, and tell me what we can actually commit to—and what needs my decision. Don’t commit to the purchase.";

export function photoBoothContext(snapshot: FinanceSnapshot | null) {
  const scenario = snapshot?.run.scenario;
  if (!snapshot || scenario?.id !== PHOTO_BOOTH_SCENARIO_ID) return null;
  const step =
    scenario.steps?.find((step) => step.id === "review") ??
    scenario.steps?.find((step) => step.id === "catch") ??
    scenario.steps?.[0];
  return {
    title: scenario.title,
    brief: scenario.brief,
    caseId: step?.case_id ?? null,
    prompt: step?.prompt?.trim() || PHOTO_BOOTH_OPENING_PROMPT,
    ready:
      scenario.status === "ready" &&
      Boolean(snapshot.cases.some((item) => item.id === step?.case_id)),
    storageKey: `finney-scenario-intro:${PHOTO_BOOTH_SCENARIO_ID}:${snapshot.organization.id}:${snapshot.run.id}`,
  };
}

export function caseReviewPayload(
  snapshot: FinanceSnapshot,
  item: FinanceSnapshot["cases"][number],
) {
  const context = photoBoothContext(snapshot);
  return {
    case_id: item.id,
    expected_version: item.version,
    ...(context?.caseId === item.id ? { message: context.prompt } : {}),
  };
}

export function shouldSubmitScenarioPrompt(
  key: string,
  shiftKey: boolean,
  composing: boolean,
  keyCode?: number,
) {
  return key === "Enter" && !shiftKey && !composing && keyCode !== 229;
}

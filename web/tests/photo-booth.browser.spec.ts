import { test, expect } from "@playwright/test";
import { buildSync } from "esbuild";
import { readFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { PHOTO_BOOTH_OPENING_PROMPT } from "../src/lib/photo-booth-scenario";
const id = "33333333-3333-4333-8333-333333333333";
const snapshot = {
  organization: {
    id: "11111111-1111-4111-8111-111111111111",
    name: "Finney test event",
  },
  run: {
    id: "22222222-2222-4222-8222-222222222222",
    name: "Practice",
    status: "active",
    currency: "USD",
    revision: 1,
    scenario: {
      id: "finney-photo-booth-v1",
      title: "HarborHacks",
      brief:
        "200 attendees. Five days to go. The team is considering a photo booth.",
      synthetic: true,
      status: "ready",
      steps: [
        {
          id: "review",
          title: "Can we afford the photo booth?",
          case_id: id,
          prompt: PHOTO_BOOTH_OPENING_PROMPT,
        },
      ],
    },
  },
  position: {
    currency: "USD",
    cash_minor: "620000",
    committed_minor: "550000",
    receivable_minor: null,
    available_minor: "70000",
    evidence_status: "synthetic_scenario",
    reconciled_at: null,
  },
  cases: [
    {
      id,
      title: "HarborHacks · photo booth decision",
      status: "needs_review",
      version: 1,
      data: {},
      updated_at: "2026-10-25",
    },
  ],
  approvals: [],
  activity: [],
  connections: [],
  improvements: {
    skill_versions: [],
    eval_runs: [],
    eval_results: [],
    promotions: [],
  },
  worker: { status: "online", last_seen_at: null },
  updated_at: "2026-10-25",
};
const script = buildSync({
  stdin: {
    contents: `import{createElement}from'react';import{createRoot}from'react-dom/client';import{FinneyCompanion}from'./src/components/finney-companion';import{LockedTutorial}from'./src/components/locked-tutorial';import{snapshotSchema}from'./src/lib/contracts';const snapshot=snapshotSchema.parse(${JSON.stringify(snapshot)});window.__CALLS__=[];createRoot(document.getElementById('fixture')).render(createElement('div',null,createElement(FinneyCompanion,{snapshot,onOpenCase:id=>window.__OPENED__=id,onAsk:(message,caseId)=>{window.__CALLS__.push({message,caseId});return true}}),createElement(LockedTutorial,{snapshot,selectedCaseId:null,tab:'cases',lastCommand:null})));`,
    loader: "tsx",
    resolveDir: process.cwd(),
  },
  bundle: true,
  write: false,
  format: "iife",
  platform: "browser",
  jsx: "automatic",
  tsconfig: resolve("tsconfig.json"),
  define: { "process.env.NODE_ENV": '"production"' },
}).outputFiles[0].text;
test("photo-booth entry offers editable scoped chat without old AV tour or automatic work", async ({
  page,
}, info) => {
  await page.goto("/desk");
  await page.setContent(
    '<html><head><link rel="stylesheet" href="/brand/mascot.css"></head><body><main id="fixture"></main></body></html>',
  );
  await page.addStyleTag({
    content:
      readFileSync(resolve("src/app/globals.css"), "utf8") +
      "#fixture{min-height:100vh;display:grid;place-items:center;padding:24px}",
  });
  await page.addScriptTag({ content: script });
  await expect(
    page.getByRole("heading", { name: "Can we afford the photo booth?" }),
  ).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(await page.evaluate(() => (window as any).__CALLS__)).toEqual([]);
  mkdirSync(resolve("../.impeccable/review"), { recursive: true });
  await page.screenshot({
    path: resolve(`../.impeccable/review/${info.project.name}-photo-intro.png`),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Start with a question" }).click();
  const composer = page.getByLabel("Ask Finney", { exact: true });
  await expect(composer).toHaveValue(PHOTO_BOOTH_OPENING_PROMPT);
  expect(await page.evaluate(() => (window as any).__CALLS__)).toEqual([]);
  await composer.fill("Review the event without committing to the purchase.");
  await composer.press("Shift+Enter");
  expect(await page.evaluate(() => (window as any).__CALLS__)).toEqual([]);
  await composer.dispatchEvent("keydown", {
    key: "Enter",
    code: "Enter",
    isComposing: true,
  });
  expect(await page.evaluate(() => (window as any).__CALLS__)).toEqual([]);
  await composer.press("Enter");
  expect(await page.evaluate(() => (window as any).__CALLS__)).toEqual([
    {
      message: "Review the event without committing to the purchase.",
      caseId: id,
    },
  ]);
  await expect(
    page.getByRole("heading", { name: "On it.", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

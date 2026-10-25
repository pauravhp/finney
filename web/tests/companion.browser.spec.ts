import { expect, test } from "@playwright/test";
import { buildSync } from "esbuild";
import { readFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
const id = "33333333-3333-4333-8333-333333333333";
const state = {
  organization: {
    id: "11111111-1111-4111-8111-111111111111",
    name: "Hack Harbor",
  },
  run: {
    id: "22222222-2222-4222-8222-222222222222",
    name: "Hack Harbor",
    currency: "USD",
    status: "active",
    revision: 1,
  },
  position: {
    currency: "USD",
    cash_minor: null,
    committed_minor: null,
    receivable_minor: null,
    available_minor: null,
    evidence_status: "unknown",
    reconciled_at: null,
  },
  cases: [
    {
      id,
      title: "Harbor AV · revised invoice",
      status: "needs_review",
      version: 2,
      updated_at: "2026-10-25",
      data: {},
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
const fixtureReply =
  "The sponsor pledge is USD 2,500.00. It is not received cash.\n\nDetails:\nThe sponsor has not sent the contribution.";
const script = buildSync({
  stdin: {
    contents: `import{createElement,useState}from'react';import{createRoot}from'react-dom/client';import{FinneyCompanion}from'./src/components/finney-companion';import{snapshotSchema}from'./src/lib/contracts';const initial=snapshotSchema.parse(${JSON.stringify(state)});function Fixture(){const[snapshot,setSnapshot]=useState(initial);const[lastCommand,setLastCommand]=useState(null);window.__TEST_STATE__=status=>setSnapshot({...initial,cases:initial.cases.map(item=>({...item,data:status==='completed'?{finding:{explanation:'The invoice has been checked.',provenance:{job_id:'fixture-job'}}}:{}})),jobs:[{id:'fixture-job',case_id:'${id}',command_type:'review_case',status,created_at:'2026-10-25'}]});window.__TEST_REPLY__=()=>setSnapshot(current=>({...current,jobs:current.jobs.map(job=>({...job,status:'completed'})),cases:current.cases.map(item=>({...item,data:{director_responses:[{id:'prior-answer',job_id:'prior-job',message:'IGNORE THIS OLDER ANSWER'},{id:'ask-job',job_id:'ask-job',message:${JSON.stringify(fixtureReply)}}]}}))}));return createElement(FinneyCompanion,{snapshot,lastCommand,onOpenCase:id=>window.__TEST_OPENED__=id,onAsk:(message,caseId)=>{window.__TEST_MESSAGE__={message,caseId};setLastCommand({jobId:'ask-job',type:'director_message',caseId});setSnapshot(current=>({...current,jobs:[{id:'ask-job',case_id:caseId,command_type:'director_message',status:'running'}],cases:current.cases.map(item=>({...item,data:{director_responses:[{id:'prior-answer',job_id:'prior-job',message:'IGNORE THIS OLDER ANSWER'}]}}))}));return true},onViewBudget:()=>window.__TEST_BUDGET__=true});}createRoot(document.getElementById('fixture')).render(createElement(Fixture));`,
    loader: "tsx",
    resolveDir: process.cwd(),
  },
  bundle: true,
  write: false,
  platform: "browser",
  format: "iife",
  jsx: "automatic",
  tsconfig: resolve("tsconfig.json"),
  define: { "process.env.NODE_ENV": '"production"' },
}).outputFiles[0].text;
test("companion presents one actual task, accepts a prompt and reflects truthful job states", async ({
  page,
}, info) => {
  await page.goto("/desk");
  await page.setContent(
    '<html><head><link rel="stylesheet" href="/brand/mascot.css"></head><body><main id="fixture"></main></body></html>',
  );
  await page.addStyleTag({
    content:
      readFileSync(resolve("src/app/globals.css"), "utf8") +
      "#fixture{min-height:100vh;background:#e2e6dd;display:grid;place-items:center;padding:24px}",
  });
  await page.addScriptTag({ content: script });
  const companion = page.getByRole("region", { name: "Finney companion" });
  await expect(
    companion.getByRole("heading", { name: "One for you." }),
  ).toBeVisible();
  await expect(companion).not.toContainText("Version");
  await expect(companion).not.toContainText("provenance");
  await page.locator('[data-tutorial="open-alert"]').click();
  expect(await page.evaluate(() => (window as any).__TEST_OPENED__)).toBe(id);
  mkdirSync(resolve("../.impeccable/review"), { recursive: true });
  await page.screenshot({
    path: resolve(
      `../.impeccable/review/${info.project.name}-companion-ready.png`,
    ),
    fullPage: true,
  });
  for (const [status, title, pose] of [
    ["queued", "Got it.", "looking"],
    ["running", "On it.", "working"],
    ["failed", "I need a hand.", "blocked"],
    ["completed", "An update for you.", "success"],
  ]) {
    await page.evaluate(
      (status) => (window as any).__TEST_STATE__(status),
      status,
    );
    await expect(
      companion.getByRole("heading", { name: title, exact: true }),
    ).toBeVisible();
    await expect(companion.locator("svg.companion-mascot")).toHaveAttribute(
      "data-pose",
      pose,
    );
    await expect(companion).not.toContainText("Paid");
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: resolve(
      `../.impeccable/review/${info.project.name}-companion-completed.png`,
    ),
    fullPage: true,
  });
  await page
    .getByLabel("Ask Finney", { exact: true })
    .fill("What sponsorship is still outstanding?");
  await page.getByRole("button", { name: "Send to Finney" }).click();
  expect(await page.evaluate(() => (window as any).__TEST_MESSAGE__)).toEqual({
    message: "What sponsorship is still outstanding?",
    caseId: id,
  });
  await expect(
    companion.getByRole("heading", { name: "On it.", exact: true }),
  ).toBeVisible();
  await expect(companion).not.toContainText("IGNORE THIS OLDER ANSWER");
  await expect(companion.getByText("Details", { exact: true })).toHaveCount(0);
  await page.evaluate(() => (window as any).__TEST_REPLY__());
  await expect(companion.locator(".director-response-primary")).toHaveText(
    "The sponsor pledge is USD 2,500.00. It is not received cash.",
  );
  await expect(companion).not.toContainText("IGNORE THIS OLDER ANSWER");
  await expect(companion.locator(".director-response-details")).toBeHidden();
  await companion.getByText("Details", { exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(companion.locator(".director-response-details")).toHaveText(
    "The sponsor has not sent the contribution.",
  );
  await expect(companion.locator(".director-response-details")).toBeVisible();
  await companion.getByText("Details", { exact: true }).focus();
  await page.keyboard.press("Enter");
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await page.screenshot({
    path: resolve(
      `../.impeccable/review/${info.project.name}-companion-answer.png`,
    ),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Back to alert" }).click();
  await expect(page.locator('[data-tutorial="open-alert"]')).toBeVisible();
});

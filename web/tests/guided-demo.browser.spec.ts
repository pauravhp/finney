import { expect, test, type Page } from "@playwright/test";
import { build } from "esbuild";
import { mkdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

// Explicit isolated UI/HTTP fixtures; no live account, provider or paid model calls.
const org = "11111111-1111-4111-8111-111111111111",
  run = "22222222-2222-4222-8222-222222222222",
  av = "33333333-3333-4333-8333-333333333333",
  mira = "44444444-4444-4444-8444-444444444444",
  source = "55555555-5555-4555-8555-555555555555";
const fixture = {
  organization: { id: org, name: "Hack Harbor" },
  run: {
    id: run,
    name: "Hack Harbor practice event",
    status: "active",
    currency: "USD",
    revision: 1,
    scenario: {
      id: "finney-mid-event-v1",
      title: "Hack Harbor",
      brief:
        "180 attendees. Five days to go. A revised invoice, a personal-card purchase and a sponsor payment still pending.",
      status: "ready",
      synthetic: true,
      steps: [
        {
          id: "catch",
          title: "Catch the changed invoice",
          case_id: av,
          prompt: "Compare the revised AV invoice with our commitment.",
        },
        {
          id: "decide",
          title: "Make the call",
          case_id: av,
          prompt:
            "Propose raising the AV budget from $800 to $1,000. Leave the decision to me.",
        },
        {
          id: "report",
          title: "See where we stand",
          case_id: mira,
          prompt: "Review Mira’s duplicate receipt and remaining obligation.",
        },
      ],
    },
  },
  position: {
    currency: "USD",
    cash_minor: "780000",
    committed_minor: "368000",
    receivable_minor: "250000",
    available_minor: "412000",
    evidence_status: "synthetic_scenario",
    reconciled_at: null,
  },
  cases: [
    {
      id: av,
      title: "Harbor AV · revised invoice",
      status: "needs_review",
      version: 2,
      updated_at: "2026-10-25T10:00:00Z",
      data: { source_ids: [source] },
    },
    {
      id: mira,
      title: "Mira · food reimbursement",
      status: "needs_review",
      version: 1,
      updated_at: "2026-10-25T10:00:00Z",
      data: {},
    },
  ],
  approvals: [],
  activity: [],
  improvements: {
    skill_versions: [],
    eval_runs: [],
    eval_results: [],
    promotions: [],
  },
  connections: [],
  source_items: [
    {
      id: source,
      source_type: "demo_bundle",
      version: 2,
      metadata: { filename: "Harbor AV — revised invoice" },
      artifact_path: `${org}/${run}/av-v2`,
    },
  ],
  reports: [],
  worker: { status: "online", last_seen_at: null },
  updated_at: "2026-10-25T10:00:00Z",
};
let script = "";
test.beforeAll(async () => {
  script = (
    await build({
      stdin: {
        contents: `import{createElement}from'react';import{createRoot}from'react-dom/client';import{Dashboard}from'./src/components/dashboard';createRoot(document.getElementById('fixture')).render(createElement(Dashboard,{configured:true,gmailAvailable:false,user:{id:'${org}',email:'director@hackharbor.example'}}));`,
        resolveDir: process.cwd(),
        loader: "tsx",
      },
      bundle: true,
      write: false,
      platform: "browser",
      format: "iife",
      jsx: "automatic",
      tsconfig: resolve("tsconfig.json"),
      define: { "process.env.NODE_ENV": '"production"', "process.env": "{}" },
      plugins: [
        {
          name: "isolated-ui-supabase",
          setup(build) {
            build.onResolve({ filter: /\/supabase\/browser$/ }, () => ({
              path: "fixture",
              namespace: "test-only",
            }));
            build.onLoad({ filter: /.*/, namespace: "test-only" }, () => ({
              loader: "js",
              contents: String.raw`export function browserSupabase(){const channel={on(){return channel},subscribe(fn){fn('SUBSCRIBED');return channel}};return{channel:()=>channel,removeChannel:()=>{},realtime:{setAuth:async()=>{}},auth:{getSession:async()=>({data:{session:null}}),onAuthStateChange:()=>({data:{subscription:{unsubscribe(){}}}})},storage:{from:()=>({download:async()=>({data:new Blob([JSON.stringify({description:'Revised invoice',documents:[{title:'Harbor AV — amended invoice',text:'Invoice HHA-104 · 25 October 2026\nOriginal charge: USD 480.00\nEquipment credit: USD 60.00\nAmount due: USD 420.00\nPayment has not been received.'},{title:'Vendor note',text:'This replaces the earlier invoice. Please do not pay both versions.'}]})]),error:null})})}}}`,
            }));
          },
        },
      ],
    })
  ).outputFiles[0].text;
});
async function mount(page: Page, status = "ready") {
  const state = structuredClone(fixture);
  state.run.scenario.status = status;
  const calls: Record<string, any>[] = [];
  await page.route("**/api/finance/scopes", (route) =>
    route.fulfill({
      json: {
        scopes: [
          {
            organization_id: org,
            organization_name: "Hack Harbor",
            role: "director",
            runs: [
              {
                id: run,
                name: "Hack Harbor practice event",
                is_demo: true,
                status: "active",
              },
            ],
          },
        ],
      },
    }),
  );
  await page.route("**/api/finance/snapshot?**", (route) =>
    route.fulfill({ json: state }),
  );
  await page.route("**/api/finance/commands", async (route) => {
    calls.push(route.request().postDataJSON());
    await route.fulfill({
      status: 202,
      json: { job_id: "66666666-6666-4666-8666-666666666666" },
    });
  });
  await page.goto("/desk");
  await page.setContent(
    '<html><head><link rel="stylesheet" href="/brand/mascot.css"></head><body><div id="fixture"></div></body></html>',
  );
  await page.addStyleTag({
    content: readFileSync(resolve("src/app/globals.css"), "utf8"),
  });
  await page.addScriptTag({ content: script });
  await expect(
    page.getByRole("heading", { name: "Hack Harbor", exact: true }),
  ).toBeVisible();
  return calls;
}
test("the walkthrough operates real scoped actions, remains optional and never marks learning passed", async ({
  page,
}, info) => {
  const calls = await mount(page);
  await expect(page.getByText("US$7,800.00", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Check the revised invoice" }),
  ).toBeEnabled();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  mkdirSync(resolve("../.impeccable/review"), { recursive: true });
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await page.screenshot({
    path: resolve(`../.impeccable/review/${info.project.name}-guided-home.png`),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Check the revised invoice" }).click();
  expect(calls[0]).toMatchObject({
    organization_id: org,
    run_id: run,
    command_type: "director_message",
    payload: { case_id: av, message: fixture.run.scenario.steps[0].prompt },
  });
  await expect(page.locator(".source-content")).toContainText("USD 420.00");
  await expect(page.locator(".source-content")).toContainText(
    "Please do not pay both versions",
  );
  await page.getByText("Add a document", { exact: true }).click();
  await expect(
    page
      .locator(".case-evidence-action")
      .getByText("Related case", { exact: true }),
  ).toHaveCount(0);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await page.screenshot({
    path: resolve(
      `../.impeccable/review/${info.project.name}-contextual-case.png`,
    ),
    fullPage: true,
  });
  await page.getByRole("button", { name: /Step 2:/ }).click();
  await page.getByRole("button", { name: "Prepare a budget proposal" }).click();
  expect(calls[1].payload.message).toBe(fixture.run.scenario.steps[1].prompt);
  await page.getByRole("button", { name: /Step 3:/ }).click();
  await page.getByRole("button", { name: "Review Mira’s purchase" }).click();
  expect(calls[2].payload.case_id).toBe(mira);
  await expect(page.getByRole("button", {name:"Generate an event report"})).toBeVisible();
  await page.getByRole("button", {name:"Generate an event report"}).click();
  await expect(page.getByRole("button", {name:"Generate report",exact:true})).toBeVisible();
  await page.getByRole("button", { name: "Skip walkthrough" }).click();
  await expect(
    page.getByRole("button", { name: "Resume walkthrough" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Resume walkthrough" }).click();
  await expect(page.getByText("Walkthrough · 3 of 4")).toBeVisible();
  await page.getByRole("button", { name: /Step 4:/ }).click();
  await page
    .getByRole("button", { name: "Inspect the learning evidence" })
    .click();
  await expect(
    page.getByRole("heading", { name: "No learned change is active yet" }),
  ).toBeVisible();
  expect(calls).toHaveLength(3);
});
test("partially seeded scenarios cannot begin agent work", async ({ page }) => {
  const calls = await mount(page, "initialized");
  await expect(
    page.getByRole("button", { name: "Preparing documents…" }),
  ).toBeDisabled();
  expect(calls).toHaveLength(0);
});

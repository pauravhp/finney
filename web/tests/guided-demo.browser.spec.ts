import { expect, test, type Page } from "@playwright/test";
import { build } from "esbuild";
import { mkdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { guidedSources } from "./fixtures/guided-source";

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
      source_type: "guided_demo",
      external_id: "guided_demo:finney-mid-event-v1:av",
      version: 2,
      metadata: {},
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
              contents: String.raw`export function browserSupabase(){const channel={on(){return channel},subscribe(fn){fn('SUBSCRIBED');return channel}};return{channel:()=>channel,removeChannel:()=>{},realtime:{setAuth:async()=>{}},auth:{getSession:async()=>({data:{session:null}}),onAuthStateChange:()=>({data:{subscription:{unsubscribe(){}}}})},storage:{from:()=>({download:async()=>({data:new Blob([JSON.stringify(${JSON.stringify(guidedSources._REVISED)})]),error:null})})}}}`,
            }));
          },
        },
      ],
    })
  ).outputFiles[0].text;
});
async function mount(page: Page, status = "ready", response?: string) {
  const state = structuredClone(fixture);
  state.run.scenario.status = status;
  if (response)
    Object.assign(state.cases[0].data, {
      director_responses: [
        {
          message: response,
          provenance: { source_case_version: 2 },
          consulted_source_ids: [source],
        },
      ],
    });
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
    const sent = route.request().postDataJSON();
    calls.push(sent);
    Object.assign(state, {jobs:[{id:"66666666-6666-4666-8666-666666666666",command_type:sent.command_type,case_id:sent.payload.case_id,status:"queued",created_at:"2026-10-25T10:01:00Z"}]});
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
  await expect(page.getByRole("button", { name: "Skip demo", exact: true })).toBeVisible();
  return {calls,state};
}

test("companion tutorial locks to real actions and waits for the exact persisted review", async ({page},info) => {
  const {calls,state} = await mount(page);
  await expect(page.getByText("You’re organizing Hack Harbor. Five days to go. Finney has an update.")).toBeVisible();
  await expect(page.getByRole("button",{name:"Skip demo",exact:true})).toBeVisible();
  await page.getByRole("button",{name:"Let’s go",exact:true}).click();
  mkdirSync(resolve("../.impeccable/companion-review"),{recursive:true});
  await page.screenshot({path:resolve(`../.impeccable/companion-review/${info.project.name}-alert.png`),fullPage:true});
  await page.locator('[data-tutorial="open-alert"]').click();
  const workspace=page.locator('.live-case-workspace');
  await expect(workspace.locator('.source-content')).toContainText('USD 420.00');
  await expect(workspace).not.toContainText(/Version |Stored agent response|Submitted by|provenance/);
  await page.locator('[data-tutorial="review-case"]').click();
  await expect.poll(()=>calls.length).toBe(1);
  expect(calls[0]).toMatchObject({command_type:'review_case',payload:{case_id:av},organization_id:org,run_id:run});
  const jobId='66666666-6666-4666-8666-666666666666';
  Object.assign(state,{jobs:[{id:jobId,command_type:'review_case',case_id:av,status:'running',created_at:'2026-10-25T10:01:00Z'}]});
  // Trigger the real fallback poll after the post-command snapshot first reports queued.
  await expect(page.locator('[data-tutorial-phase="waiting"]')).toBeVisible();
  await expect(workspace.locator('[data-pose="working"]')).toBeVisible();
  await page.screenshot({path:resolve(`../.impeccable/companion-review/${info.project.name}-working.png`),fullPage:true});
  Object.assign((state as any).jobs[0],{status:'completed'});
  await page.waitForTimeout(2800);
  await expect(page.locator('[data-tutorial-phase="waiting"]')).toBeVisible();
  Object.assign(state.cases[0].data,{finding:{kind:'prepared_agent_review',verification:'unverified_model_recommendation',decision:'reported_liability',explanation:'The new invoice is $420, down from $480. Nothing has been paid.',provenance:{job_id:jobId,actor_trace_id:'recorded-trace',source_case_version:2}}});
  // A completed job with delayed persistence still needs a refresh. Reload tests actual saved phase restoration.
  await page.evaluate(()=>window.dispatchEvent(new Event('online')));
  await expect(page.locator('[data-tutorial-phase="budget"]')).toBeVisible({timeout:10000});
  await page.screenshot({path:resolve(`../.impeccable/companion-review/${info.project.name}-result.png`),fullPage:true});
  await page.locator('[data-tutorial="view-budget"]').click();
  await expect(page.getByText('You’re ready.',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Done',exact:true}).click();
  await expect(page.getByRole('button',{name:'Skip demo',exact:true})).toHaveCount(0);
  await expect(page.getByText('US$7,800.00',{exact:true})).toBeVisible();
  expect(calls).toHaveLength(1);
});

test("skip unlocks the actual app; internal fields stay out of the case",async({page},info)=>{
 const {calls}=await mount(page);
 await page.getByRole('button',{name:'Skip demo',exact:true}).click();
 await page.locator('[data-tutorial="open-alert"]').click();
 await expect(page.locator('.source-content')).toContainText('No payment has been sent.');
 await expect(page.locator('.live-case-workspace')).not.toContainText(/Version |provenance|Submitted by|Stored agent response/);
 await page.getByText('Add a document',{exact:true}).click();
 await expect(page.locator('.case-evidence-action').getByText('Related case',{exact:true})).toHaveCount(0);
 await page.evaluate(()=>scrollTo(0,0));
 await page.screenshot({path:resolve(`../.impeccable/companion-review/${info.project.name}-clean-case.png`),fullPage:true});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 expect(calls).toHaveLength(0);
});

test("partially prepared events cannot enqueue a review",async({page})=>{
 const {calls}=await mount(page,'initialized');
 await page.getByRole('button',{name:'Skip demo',exact:true}).click();
 const button=page.locator('[data-tutorial="open-alert"]');
 if(await button.isEnabled()){
   await button.click();
   await expect(page.locator('[data-tutorial="review-case"]')).toBeDisabled();
 }
 expect(calls).toHaveLength(0);
});

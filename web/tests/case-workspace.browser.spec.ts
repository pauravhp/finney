import { expect, test } from "@playwright/test";
import { build } from "esbuild";
import { mkdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

test.skip(
  Boolean(process.env.FINANCE_AUTH_BROWSER_FIXTURE),
  "Explicit local component/storage fixture.",
);
const org = "11111111-1111-4111-8111-111111111111",
  run = "22222222-2222-4222-8222-222222222222",
  id = "33333333-3333-4333-8333-333333333333",
  original = "44444444-4444-4444-8444-444444444444",
  revised = "55555555-5555-4555-8555-555555555555";
const state = {
  organization: { id: org, name: "TEST ONLY event" },
  run: {
    id: run,
    name: "TEST ONLY run",
    status: "active",
    currency: "USD",
    revision: 2,
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
      title: "TEST ONLY revised AV invoice",
      status: "needs_review",
      version: 2,
      updated_at: "2026-10-25T00:00:00Z",
      data: {
        source_ids: [original, revised],
        finding: {
          decision: "investigate",
          verification: "unverified_model_recommendation",
          explanation:
            "TEST ONLY: the revised invoice changes the amount. The director rejected the previous proposal; a revision does not grant approval.",
          proposed_action: {
            action: "investigate",
            amount_minor: "42000",
            currency: "USD",
          },
          blocking_requirements: [
            { stage: "execution", requirement: "human_approval" },
          ],
        },
      },
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
      id: original,
      source_type: "upload",
      version: 1,
      external_id: "TEST-ONLY-same-document",
      artifact_path: `${org}/${run}/original`,
    },
    {
      id: revised,
      source_type: "upload",
      version: 2,
      external_id: "TEST-ONLY-same-document",
      artifact_path: `${org}/${run}/revised`,
    },
  ],
  reports: [],
  worker: { status: "online", last_seen_at: null },
  updated_at: "2026-10-25T00:00:00Z",
};
let script = "";
test.beforeAll(async () => {
script = (await build({
  stdin: {
    contents: `import {createElement} from 'react'; import {createRoot} from 'react-dom/client'; import {CaseWorkspace} from './src/components/case-workspace'; import {snapshotSchema} from './src/lib/contracts'; const snapshot=snapshotSchema.parse(${JSON.stringify(state)}); createRoot(document.getElementById('fixture')).render(createElement(CaseWorkspace,{item:snapshot.cases[0],snapshot,onBack:()=>{},onReview:()=>{},busy:false,canWork:true,decisions:null,evidenceForm:createElement('p',null,'TEST ONLY upload surface')}));`,
    resolveDir: process.cwd(),
    loader: "tsx",
  },
  bundle: true,
  write: false,
  platform: "browser",
  format: "iife",
  jsx: "automatic",
  tsconfig: resolve("tsconfig.json"),
  define: { "process.env.NODE_ENV": '"production"' },
  plugins: [
    {
      name: "explicit-private-storage-fixture",
      setup(build) {
        build.onResolve({ filter: /\/supabase\/browser$/ }, () => ({
          path: "fixture-storage",
          namespace: "test-only",
        }));
        build.onLoad({ filter: /.*/, namespace: "test-only" }, () => ({
          contents: `export function browserSupabase(){return {storage:{from:()=>({download:async path=>({data:new Blob([JSON.stringify({text:path.endsWith('original')?'TEST ONLY original invoice: USD 500.00':'TEST ONLY revised invoice: USD 420.00. <script>window.injected=true</script>'})],{type:'application/json'}),error:null})})}}}`,
          loader: "js",
        }));
      },
    },
  ],
})).outputFiles[0].text;
});

test("versioned source evidence stays beside the decision and source markup cannot execute", async ({
  page,
}, info) => {
  await page.goto("/desk");
  await page.setContent(
    '<html><head><link rel="stylesheet" href="/brand/mascot.css"></head><body><main id="fixture"></main></body></html>',
  );
  await page.addStyleTag({
    content:
      readFileSync(resolve("src/app/globals.css"), "utf8") +
      "#fixture{max-width:1200px;margin:auto;padding:28px}@media(max-width:680px){#fixture{padding:20px}}",
  });
  await page.addScriptTag({ content: script });
  await expect(page.locator(".source-content")).toContainText("USD 500.00");
  await page
    .locator(`button[data-source-id="${revised}"][data-source-version="2"]`)
    .click();
  await expect(page.locator(".source-content")).toContainText("USD 420.00");
  await expect(page.locator(".source-content")).toContainText(
    "<script>window.injected=true</script>",
  );
  expect(await page.evaluate(() => Object.hasOwn(window, "injected"))).toBe(
    false,
  );
  await expect(
    page.getByText("Proposed amount", { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  if (info.project.name === "mobile") {
    const decision = await page.locator(".live-case-decision").boundingBox();
    const evidence = await page.locator(".live-case-evidence").boundingBox();
    expect(decision!.y).toBeLessThan(evidence!.y);
  }
  mkdirSync(resolve("../.state/ui-review"), { recursive: true });
  await page.screenshot({
    path: resolve(
      `../.state/ui-review/v7-${info.project.name}-case-fixture.png`,
    ),
    fullPage: true,
  });
});

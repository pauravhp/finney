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
  script = (
    await build({
      stdin: {
        contents: `import {createElement,useLayoutEffect} from 'react'; import {createRoot} from 'react-dom/client'; import {CaseWorkspace} from './src/components/case-workspace'; import {snapshotSchema} from './src/lib/contracts'; const snapshot=snapshotSchema.parse(${JSON.stringify(state)}); const root=createRoot(document.getElementById('fixture')); function Fixture({revision}){useLayoutEffect(()=>{if(revision)window.__TEST_ONLY_COMMIT__={text:document.querySelector('.source-content')?.textContent??null,loadState:document.querySelector('.source-paper-live')?.getAttribute('data-source-load-state')};},[revision]);return createElement(CaseWorkspace,{item:snapshot.cases[0],snapshot,onBack:()=>{},onReview:()=>{},busy:false,canWork:true,decisions:null,evidenceForm:createElement('p',null,'TEST ONLY upload surface')});} root.render(createElement(Fixture,{revision:0})); window.__TEST_ONLY_REPLACE_PATH__=path=>{snapshot.source_items=snapshot.source_items.map(row=>row.id==='${revised}'?{...row,artifact_path:path}:row);root.render(createElement(Fixture,{revision:1}));}; window.__TEST_ONLY_LATER_REPLY__=()=>{snapshot.cases[0].data.finding={...snapshot.cases[0].data.finding,provenance:{source_case_version:8},explanation:'TEST ONLY stale review says manually fix the record.',proposed_action:{action:'investigate',amount_minor:'50000',currency:'USD'}};snapshot.cases[0].data.director_responses=[{id:'TEST-OLD',message:'TEST ONLY earlier stored conversation.',provenance:{source_case_version:10}},{id:'TEST-NEW',message:'TEST ONLY latest: revised 420 recorded, budget rejected, cash unknown.',provenance:{source_case_version:12}}];root.render(createElement(Fixture,{revision:2}));};`,
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
              contents: `export function browserSupabase(){return {storage:{from:()=>({download:async path=>{if(window.__TEST_ONLY_HOLD_SUFFIX__&&path.endsWith(window.__TEST_ONLY_HOLD_SUFFIX__))await new Promise(resolve=>{window.__TEST_ONLY_RELEASE__=resolve});return {data:new Blob([JSON.stringify({text:path.endsWith('original')?'TEST ONLY original invoice: USD 500.00':path.endsWith('replacement')?'TEST ONLY alternate artifact: USD 390.00':'TEST ONLY revised invoice: USD 420.00. <script>window.injected=true</script>'})],{type:'application/json'}),error:null};}})}}}`,
              loader: "js",
            }));
          },
        },
      ],
    })
  ).outputFiles[0].text;
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

test("a delayed source switch never pairs a new identity or path with old content", async ({
  page,
}) => {
  await page.goto("/desk");
  await page.setContent('<main id="fixture"></main>');
  await page.addScriptTag({ content: script });
  await expect(page.locator(".source-content")).toContainText("USD 500.00");
  await page.evaluate(() =>
    Object.assign(window, { __TEST_ONLY_HOLD_SUFFIX__: "revised" }),
  );
  await page.locator(`button[data-source-id="${revised}"]`).click();
  await expect(page.locator(".source-paper-live")).toHaveAttribute(
    "data-source-version",
    "2",
  );
  await expect(page.locator(".source-paper-live")).toHaveAttribute(
    "data-source-load-state",
    "loading",
  );
  await expect(page.locator(".source-content")).toHaveCount(0);
  await page.waitForFunction(
    () => typeof (window as any).__TEST_ONLY_RELEASE__ === "function",
  );
  await page.evaluate(() => (window as any).__TEST_ONLY_RELEASE__());
  await expect(page.locator(".source-content")).toHaveAttribute(
    "data-loaded-source-id",
    revised,
  );
  await expect(page.locator(".source-content")).toContainText("USD 420.00");
  // Keep source id/version (and therefore the React key) unchanged while its
  // artifact reference changes. Inspect the committed DOM before passive effects.
  await page.evaluate((path) => {
    Object.assign(window, {
      __TEST_ONLY_HOLD_SUFFIX__: "replacement",
      __TEST_ONLY_RELEASE__: null,
    });
    (window as any).__TEST_ONLY_REPLACE_PATH__(path);
  }, `${org}/${run}/replacement`);
  await page.waitForFunction(() =>
    Boolean((window as any).__TEST_ONLY_COMMIT__),
  );
  expect(
    await page.evaluate(() => (window as any).__TEST_ONLY_COMMIT__),
  ).toEqual({ text: null, loadState: "loading" });
  await expect(page.locator(".source-content")).toHaveCount(0);
  await page.waitForFunction(
    () => typeof (window as any).__TEST_ONLY_RELEASE__ === "function",
  );
  await page.evaluate(() => (window as any).__TEST_ONLY_RELEASE__());
  await expect(page.locator(".source-content")).toContainText("USD 390.00");
  await expect(page.locator(".source-content")).not.toContainText("USD 420.00");
  await expect(page.locator(".source-content")).toHaveAttribute(
    "data-loaded-source-version",
    "2",
  );
});

test("a later reply leads without stale amounts or audit chrome in the primary view", async ({
  page,
}) => {
  await page.goto("/desk");
  await page.setContent(
    '<html><head><link rel="stylesheet" href="/brand/mascot.css"></head><body><main id="fixture"></main></body></html>',
  );
  await page.addStyleTag({
    content:
      readFileSync(resolve("src/app/globals.css"), "utf8") +
      "#fixture{max-width:1200px;margin:auto;padding:20px}",
  });
  await page.addScriptTag({ content: script });
  await expect(page.locator(".source-content")).toContainText("USD 500.00");
  await page.evaluate(() => (window as any).__TEST_ONLY_LATER_REPLY__());
  const latest = page.locator(".case-latest-response");
  await expect(latest).toContainText(
    "revised 420 recorded, budget rejected, cash unknown",
  );
  await expect(
    page.getByText("manually fix the record", { exact: false }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Earlier proposed amount", { exact: true }),
  ).toHaveCount(0);
  await expect(page.locator(".live-case-heading")).not.toContainText("Version");
  await expect(page.locator(".live-case-heading")).not.toContainText("Updated");
  await expect(
    page.getByText("TEST ONLY earlier stored conversation.", { exact: true }),
  ).toBeHidden();
  await page.locator(".case-conversation > summary").click();
  await expect(
    page.getByText("TEST ONLY earlier stored conversation.", { exact: true }),
  ).toBeVisible();
});

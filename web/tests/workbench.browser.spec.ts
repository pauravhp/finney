import { expect, test, type Page } from "@playwright/test";
import { buildSync } from "esbuild";
import { mkdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

// Explicit component/HTTP fixtures. No account, provider, model or database calls.
test.skip(
  Boolean(process.env.FINANCE_AUTH_BROWSER_FIXTURE),
  "Component fixtures run with the normal production build.",
);
const scope = {
  organization_id: "d19587c6-6535-4455-b4cd-ea4819845ec1",
  run_id: "d19587c6-6535-4455-b4cd-ea4819845ec2",
};
const decisionId = "d19587c6-6535-4455-b4cd-ea4819845ec3";
const jobId = "d19587c6-6535-4455-b4cd-ea4819845ec4";

const script = buildSync({
  stdin: {
    contents: `
import { createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { Workbench, BudgetWorkbench } from './src/components/workbench';
const scope=${JSON.stringify(scope)};
async function onCommand(command_type,payload){
 const response=await fetch('/api/finance/commands',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...scope,command_type,payload,idempotency_key:'TEST-ONLY-command-key'})});
 if(!response.ok)return false; document.getElementById('fixture-status').textContent='Work queued; completion not confirmed'; return true;
}
const props={scope,currency:'USD',canEdit:true,onRefresh:async()=>{}};
createRoot(document.getElementById('root')).render(createElement('main',null,
 createElement(Workbench,{...props,cases:[],busy:false,onCommand}),
 createElement(BudgetWorkbench,{...props,canDecide:true,budget:{lines:[{id:'TEST-ONLY-line',name:'TEST ONLY food',currency:'USD',allocated_minor:'100000',committed_minor:'20000',remaining_minor:'80000',version:3}],decisions:[{id:'${decisionId}',name:window.__TEST_ONLY_LONG_BUDGET_NAME__??'TEST ONLY supplies',currency:'USD',allocated_minor:'30000',status:'pending',rationale:'TEST ONLY planning proposal'}]}})
));`,
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
}).outputFiles[0].text;

async function mount(page: Page, longBudgetName?: string) {
  await page.goto("/");
  await page.setContent(
    '<!doctype html><html><head></head><body><div id="root"></div><p id="fixture-status" role="status"></p></body></html>',
  );
  await page.addStyleTag({
    content:
      readFileSync(resolve("src/app/globals.css"), "utf8") +
      "main{max-width:1060px;margin:auto;padding:24px}.fixture{color:var(--muted)}",
  });
  if (longBudgetName)
    await page.evaluate((name) => {
      Object.assign(window, { __TEST_ONLY_LONG_BUDGET_NAME__: name });
    }, longBudgetName);
  await page.addScriptTag({ content: script });
  await expect(
    page.getByRole("heading", { name: "Work with Finney" }),
  ).toBeVisible();
}

test("a 120-character unbroken budget name wraps inside the mobile decision row", async ({
  page,
}, info) => {
  test.skip(
    info.project.name !== "mobile",
    "Targeted mobile overflow regression.",
  );
  const name = "X".repeat(120);
  await mount(page, name);
  const title = page
    .locator(".budget-decisions strong")
    .filter({ hasText: name });
  await expect(title).toBeVisible();
  const bounds = await title.evaluate((element) => ({
    overflowWrap: getComputedStyle(element).overflowWrap,
    linesFit: [...element.getClientRects()].every(
      (rect) => rect.left >= 0 && rect.right <= innerWidth,
    ),
    documentFits: document.documentElement.scrollWidth <= innerWidth,
  }));
  expect(bounds).toEqual({
    overflowWrap: "anywhere",
    linesFit: true,
    documentFits: true,
  });
  const directory = resolve("../.state/ui-review");
  mkdirSync(directory, { recursive: true });
  await page.screenshot({
    path: resolve(directory, "workbench-mobile-long-name.png"),
    fullPage: true,
  });
});

test("a request to Finney queues work without claiming approval or completion", async ({
  page,
}) => {
  const bodies: unknown[] = [];
  await page.route("**/api/finance/commands", async (route) => {
    bodies.push(route.request().postDataJSON());
    await route.fulfill({
      status: 202,
      json: { job_id: jobId, status: "queued" },
    });
  });
  await mount(page);
  await page
    .getByLabel("What should Finney work on?")
    .fill(
      "TEST ONLY compare catering quotes and identify missing payer evidence",
    );
  await page
    .getByRole("button", { name: "Queue request", exact: true })
    .click();
  expect(bodies).toEqual([
    {
      ...scope,
      command_type: "director_message",
      idempotency_key: "TEST-ONLY-command-key",
      payload: {
        message:
          "TEST ONLY compare catering quotes and identify missing payer evidence",
      },
    },
  ]);
  await expect(
    page.getByText("Work queued; completion not confirmed"),
  ).toBeVisible();
  await expect(page.getByLabel("What should Finney work on?")).toHaveValue("");
});

test("manual entry preserves precise money and sends a reported record for queued review", async ({
  page,
}, info) => {
  const bodies: unknown[] = [];
  await page.route("**/api/finance/commands", async (route) => {
    bodies.push(route.request().postDataJSON());
    await route.fulfill({
      status: 202,
      json: { job_id: jobId, status: "queued" },
    });
  });
  await mount(page);
  await page.getByRole("button", { name: "Add a record", exact: true }).click();
  await page
    .getByLabel("Expense or expected income")
    .fill("TEST ONLY catering quote");
  await page
    .getByLabel("Amount (USD)", { exact: true })
    .fill("90071992547409.93");
  await page.getByRole("button", { name: "Queue record review" }).click();
  expect(bodies).toEqual([
    {
      ...scope,
      command_type: "intake",
      idempotency_key: "TEST-ONLY-command-key",
      payload: {
        source: "manual",
        description: "TEST ONLY catering quote",
        amount_minor: "9007199254740993",
        currency: "USD",
        direction: "payable",
      },
    },
  ]);
  await expect(
    page.getByText("Work queued; completion not confirmed"),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: `test-results/${info.project.name}-workbench.png`,
    fullPage: true,
  });
});

test("stored-document recovery retries the exact queued command without uploading twice", async ({
  page,
}) => {
  let uploads = 0;
  const retried: unknown[] = [];
  const retry = {
    ...scope,
    command_type: "intake",
    payload: {
      source: "upload",
      artifact_path: `${scope.organization_id}/${scope.run_id}/uploads/test-only`,
      filename: "test-only.txt",
      size: 16,
      content_type: "text/plain",
    },
    idempotency_key: "TEST-ONLY-upload-key",
  };
  await page.route("**/api/finance/upload", async (route) => {
    uploads++;
    await route.fulfill({
      status: 503,
      json: {
        error: "Document stored; review could not be queued. Retry review.",
        retry_command: retry,
      },
    });
  });
  await page.route("**/api/finance/commands", async (route) => {
    retried.push(route.request().postDataJSON());
    await route.fulfill({
      status: 202,
      json: { job_id: jobId, status: "queued" },
    });
  });
  await mount(page);
  await page
    .getByRole("button", { name: "Upload a document", exact: true })
    .click();
  await page.getByLabel("Invoice, agreement or receipt").setInputFiles({
    name: "test-only.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("TEST ONLY receipt"),
  });
  await page.getByRole("button", { name: "Upload & queue review" }).click();
  await expect(
    page.getByText("The original document is stored.", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Retry document review" }).click();
  expect(uploads).toBe(1);
  expect(retried).toEqual([retry]);
  await expect(
    page
      .getByRole("status")
      .filter({ hasText: "Stored document review queued" }),
  ).toBeVisible();
});

test("a budget proposal is separate from an explicit director approval", async ({
  page,
}) => {
  const bodies: Record<string, unknown>[] = [];
  await page.route("**/api/finance/budget", async (route) => {
    bodies.push(route.request().postDataJSON());
    await route.fulfill({ status: 200, json: { status: "pending" } });
  });
  await mount(page);
  await page.getByRole("button", { name: "Propose allocation" }).click();
  await page.getByLabel("New category name").fill("TEST ONLY travel");
  await page.getByLabel("Total allocation (USD)").fill("123.45");
  await page
    .getByLabel("Reason for this allocation")
    .fill("TEST ONLY planning evidence");
  await page.getByRole("button", { name: "Save budget proposal" }).click();
  await expect(
    page.getByText("Budget proposal saved.", { exact: false }),
  ).toBeVisible();
  expect(bodies).toHaveLength(1);
  expect(bodies[0]).toMatchObject({
    ...scope,
    operation: "propose",
    arguments: {
      new_name: "TEST ONLY travel",
      allocated_minor: "12345",
      rationale: "TEST ONLY planning evidence",
    },
  });
  await page
    .getByRole("button", { name: "Approve allocation", exact: true })
    .click();
  expect(bodies[1]).toEqual({
    ...scope,
    operation: "decide",
    decision_id: decisionId,
    decision: "approve",
  });
  await expect(
    page.getByText("Budget allocation approved.", { exact: true }),
  ).toBeVisible();
});

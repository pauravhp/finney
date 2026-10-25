import { expect, test } from "@playwright/test";
import { buildSync } from "esbuild";
import { mkdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

// Explicit local component/HTTP fixture. No wallet, account or provider requests.
test.skip(
  Boolean(process.env.FINANCE_AUTH_BROWSER_FIXTURE),
  "Normal-build component fixture.",
);
const proposalId = "d19587c6-6535-4455-b4cd-ea4819845ec1";
const paymentId = "d19587c6-6535-4455-b4cd-ea4819845ec2";
const script = buildSync({
  stdin: {
    contents: `
import { createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { PaymentExecution } from './src/components/payment-execution';
import { DirectorResponses } from './src/components/director-responses';
const proposal={id:'${proposalId}',action_hash:'TEST-ONLY-action-hash',action:{type:'payment'},status:'reserved',required_approvals:2,approval_count:2,decisions:[],expires_at:'2099-01-01T00:00:00Z',created_at:'2026-10-25T00:00:00Z'};
const payment={id:'${paymentId}',proposal_id:proposal.id,status:'uncertain',provider_reference:'wallet-request:TEST-ONLY-request',approval_url:'https://wallet.example.invalid/approve/TEST-ONLY-request',can_reconcile:true,created_at:'2026-10-25T00:00:00Z',updated_at:'2026-10-25T00:00:00Z'};
async function onExecute(proposalId){
 const response=await fetch('/api/finance/commands',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command_type:'execute_payment',payload:{proposal_id:proposalId}})});
 if(response.ok)document.getElementById('queue-status').textContent='Reconciliation queued; payment still unconfirmed';return response.ok;
}
createRoot(document.getElementById('root')).render(createElement('main',null,
createElement('article',{className:'proposal'},createElement('h2',null,'TEST ONLY organizer reimbursement'),createElement(PaymentExecution,{proposal,payments:[payment],jobs:[],canOperate:true,isDemo:false,busy:false,onExecute})),
createElement('article',{className:'proposal'},createElement(DirectorResponses,{responses:[{id:'TEST-ONLY-reply',message:'TEST ONLY director reply.\\nThe next step is to review the attached budget. <script>fixture</script>',consulted_source_ids:['${proposalId}'],job_id:'TEST-ONLY-director-job',actor_trace_id:'TEST-ONLY-director-trace',provenance:{model:'TEST-ONLY-model'}}]}))));`,
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

test("pending Wallet approval exposes a safe link and queues reconciliation of exactly the same proposal", async ({
  page,
}, info) => {
  const commands: unknown[] = [];
  await page.route("**/api/finance/commands", async (route) => {
    commands.push(route.request().postDataJSON());
    await route.fulfill({
      status: 202,
      json: { status: "queued", job_id: "TEST-ONLY-job" },
    });
  });
  await page.goto("/desk");
  await page.setContent(
    '<!doctype html><html><body><div id="root"></div><p id="queue-status" role="status"></p></body></html>',
  );
  await page.addStyleTag({
    content:
      readFileSync(resolve("src/app/globals.css"), "utf8") +
      "main{max-width:960px;margin:auto;padding:24px}",
  });
  await page.addScriptTag({ content: script });
  await expect(
    page.getByRole("heading", { name: "Payment execution" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Open Wallet approval" }),
  ).toHaveAttribute(
    "href",
    "https://wallet.example.invalid/approve/TEST-ONLY-request",
  );
  await expect(page.getByText(paymentId)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Finney’s replies" }),
  ).toBeVisible();
  await expect(page.locator(".director-response-text")).toHaveText(
    "TEST ONLY director reply.\nThe next step is to review the attached budget. <script>fixture</script>",
  );
  expect(
    await page
      .locator(".director-response-text")
      .evaluate((element) => getComputedStyle(element).whiteSpace),
  ).toBe("pre-wrap");
  await expect(page.locator(".director-response-text script")).toHaveCount(0);
  await page.getByRole("button", { name: "Check existing payment" }).click();
  await expect(page.locator("#queue-status")).toHaveText(
    "Reconciliation queued; payment still unconfirmed",
  );
  expect(commands).toEqual([
    { command_type: "execute_payment", payload: { proposal_id: proposalId } },
  ]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  const directory = resolve("../.state/ui-review");
  mkdirSync(directory, { recursive: true });
  await page.screenshot({
    path: resolve(directory, `payment-execution-${info.project.name}.png`),
    fullPage: true,
  });
});

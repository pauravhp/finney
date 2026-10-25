import { expect, test, type Page } from "@playwright/test";
import { buildSync } from "esbuild";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// Actual React component + Supabase Auth/Storage SDK; every provider response is a fixture.
const origin = "https://finance-procedure.test.invalid";
const scope = {
  organization_id: "d19587c6-6535-4455-b4cd-ea4819845ec1",
  run_id: "d19587c6-6535-4455-b4cd-ea4819845ec2",
};
const prior = "Read the supplied receipt once before asking who paid.";
const next =
  "Read each current source version once. Distinguish the payer from the payment recipient. <script>fixture</script>";
const skill = (body: string) =>
  `# Expense procedure\n\n## Investigation procedure\n\n${body}\n\n## Authority boundary\n\nNever approve or execute a payment.\n`;
const hash = (body: string) => createHash("sha256").update(body).digest("hex");
const version = (id: string, body: string) => ({
  id,
  skill_name: "organizer-expenses",
  artifact_path: `${scope.organization_id}/${scope.run_id}/artifacts/${hash(body)}/${id}.md`,
  content_sha256: hash(body),
  metadata: {
    origin: "actual-benchmark-shape",
    generation: { evidence: { method: "harness2" } },
  },
});
const baseline = version("baseline", skill(prior));
const row = {
  ...version("candidate", skill(next)),
  parent_version_id: baseline.id,
};
const issuedAt = Math.floor(Date.now() / 1000);
const user = {
  id: "d19587c6-6535-4455-b4cd-ea4819845ec9",
  email: "procedure@example.test",
  aud: "authenticated",
  role: "authenticated",
  created_at: "2026-10-25T00:00:00Z",
};
const encode = (v: unknown) =>
  Buffer.from(JSON.stringify(v)).toString("base64url");
const token = `${encode({ alg: "HS256", typ: "JWT" })}.${encode({ sub: user.id, aud: "authenticated", role: "authenticated", iat: issuedAt, exp: issuedAt + 3600 })}.${Buffer.from("not-a-real-signature").toString("base64url")}`;
const script = buildSync({
  stdin: {
    contents: `
import {createElement} from 'react'; import {createRoot} from 'react-dom/client';
import {Procedure} from './src/components/procedure'; import {browserSupabase} from './src/lib/supabase/browser';
const root=createRoot(document.getElementById('root'));
window.renderProcedureFixture=(props)=>root.render(createElement('main',null,createElement('article',{className:'learning-record'},createElement(Procedure,props))));
(async()=>{const {error}=await browserSupabase().auth.setSession({access_token:${JSON.stringify(token)},refresh_token:'fixture-refresh'});if(error)throw error;window.renderProcedureFixture(window.procedureFixture);})();`,
    resolveDir: process.cwd(),
    loader: "tsx",
  },
  bundle: true,
  write: false,
  platform: "browser",
  format: "iife",
  jsx: "automatic",
  tsconfig: resolve("tsconfig.json"),
  define: {
    "process.env.NODE_ENV": '"production"',
    "process.env.NEXT_PUBLIC_SUPABASE_URL": JSON.stringify(origin),
    "process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY":
      '"sb_publishable_procedure_fixture"',
  },
}).outputFiles[0].text;

async function mount(
  page: Page,
  props: Record<string, unknown>,
  respond: (path: string) => { status?: number; body: string },
) {
  const reads: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route(`${origin}/**`, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/auth/v1/user")
      return route.fulfill({ status: 200, json: user });
    if (url.pathname.startsWith("/storage/v1/")) {
      expect(route.request().headers().authorization).toBe("Bearer " + token);
      const path = decodeURIComponent(
        url.pathname.split("/finance-artifacts/")[1] ?? "",
      );
      reads.push(path);
      const result = respond(path);
      return route.fulfill({
        status: result.status ?? 200,
        contentType: "text/plain; charset=utf-8",
        body: result.body,
      });
    }
    return route.abort();
  });
  await page.goto("/desk");
  await page.setContent(
    '<!doctype html><html><head></head><body><div id="root"></div></body></html>',
  );
  await page.addStyleTag({
    content:
      readFileSync(resolve("src/app/globals.css"), "utf8") +
      "main{max-width:1060px;margin:auto;padding:24px}",
  });
  await page.evaluate((props) => {
    Object.assign(window, { procedureFixture: props });
  }, props);
  await page.addScriptTag({ content: script });
  await expect(page.getByRole("button")).toBeVisible();
  return { reads, errors };
}

test("artifact-only candidate and parent show their actual verified procedure diff on demand", async ({
  page,
}, info) => {
  const { reads, errors } = await mount(
    page,
    { row, baseline, scope },
    (path) => ({
      body: path === row.artifact_path ? skill(next) : skill(prior),
    }),
  );
  expect(reads).toEqual([]);
  await page.getByRole("button", { name: "Compare stored procedures" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Showing verified stored procedure text.",
  );
  await expect(
    page.locator(".procedure-comparison").getByText(prior, { exact: true }),
  ).toBeVisible();
  await expect(
    page.locator(".procedure-comparison").getByText(next, { exact: true }),
  ).toBeVisible();
  await expect(page.locator("details > pre")).toContainText("-" + prior);
  await expect(page.locator("details > pre")).toContainText("+" + next);
  await expect(page.locator(".procedure-comparison script")).toHaveCount(0);
  expect(reads.sort()).toEqual(
    [row.artifact_path, baseline.artifact_path].sort(),
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: `test-results/${info.project.name}-stored-procedure-diff.png`,
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("denied baseline exposes a safe retry and never fabricates a comparison", async ({
  page,
}) => {
  let denied = true;
  const { reads, errors } = await mount(
    page,
    { row, baseline, scope },
    (path) =>
      path === baseline.artifact_path && denied
        ? { status: 403, body: "PRIVATE storage provider detail" }
        : { body: path === row.artifact_path ? skill(next) : skill(prior) },
  );
  await page.getByRole("button", { name: "Compare stored procedures" }).click();
  await expect(
    page.locator(".learning-record").getByRole("alert"),
  ).toContainText("baseline procedure is unavailable to this account");
  await expect(page.getByText("PRIVATE storage provider detail")).toHaveCount(
    0,
  );
  await expect(
    page.getByText("Inspect procedure diff", { exact: true }),
  ).toHaveCount(0);
  denied = false;
  await page.getByRole("button", { name: "Compare stored procedures" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Showing verified stored procedure text.",
  );
  expect(reads.length).toBe(4);
  expect(errors).toEqual([]);
});

test("foreign parent is rejected before either private Storage read", async ({
  page,
}) => {
  const { reads } = await mount(
    page,
    {
      row,
      baseline: {
        ...baseline,
        artifact_path: `${scope.organization_id}/foreign/artifacts/baseline.md`,
      },
      scope,
    },
    () => ({ body: "must not read" }),
  );
  await page.getByRole("button", { name: "Compare stored procedures" }).click();
  await expect(
    page.locator(".learning-record").getByRole("alert"),
  ).toContainText("baseline artifact path does not belong to this run");
  expect(reads).toEqual([]);
  await expect(page.locator(".procedure-comparison")).toHaveCount(0);
});

test("a missing parent shows the stored candidate without inventing a baseline diff", async ({
  page,
}) => {
  const { reads } = await mount(page, { row, scope }, () => ({
    body: skill(next),
  }));
  await expect(page.getByText(/baseline version is unavailable/)).toBeVisible();
  await page
    .getByRole("button", { name: "Inspect private procedure artifact" })
    .click();
  await expect(page.getByRole("status")).toHaveText(
    "Showing verified stored procedure text.",
  );
  await expect(
    page.getByText("Inspect candidate procedure", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Inspect procedure diff", { exact: true }),
  ).toHaveCount(0);
  expect(reads).toEqual([row.artifact_path]);
});

test("a mismatched candidate checksum prevents displaying unverified artifact text", async ({
  page,
}) => {
  await mount(page, { row, baseline, scope }, (path) => ({
    body:
      path === row.artifact_path
        ? "UNVERIFIED altered procedure"
        : skill(prior),
  }));
  await page.getByRole("button", { name: "Compare stored procedures" }).click();
  await expect(
    page.locator(".learning-record").getByRole("alert"),
  ).toContainText("candidate artifact does not match its stored checksum");
  await expect(page.getByText("UNVERIFIED altered procedure")).toHaveCount(0);
  await expect(page.locator(".procedure-comparison")).toHaveCount(0);
});

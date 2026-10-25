import { expect, test } from "@playwright/test";

test.skip(
  Boolean(process.env.FINANCE_AUTH_BROWSER_FIXTURE),
  "Unconfigured-build checks run separately from the explicit Auth fixture build.",
);

test("unconfigured workspace stays honest and usable at every viewport", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/desk");
  if (info.project.name === "mobile") await page.getByRole("button", {name: "Open navigation"}).click();
  await page.getByRole("button", {name: "Overview", exact: true}).click();
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Connect your event to begin" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Email sign-in setup" }),
  ).toHaveAttribute("href", "https://supabase.com/docs/guides/auth/passwords");
  await expect(page.getByLabel("Password", { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Continue with Google" }),
  ).toHaveCount(0);
  await expect(page.getByText("Unknown", { exact: true })).toHaveCount(4);
  await expect(
    page.getByRole("button", { name: "Refresh forecast" }),
  ).toBeDisabled();
  await expect(page.getByText("$0.00", { exact: true })).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: `test-results/${info.project.name}-overview.png`,
    fullPage: true,
  });
  if (info.project.name === "mobile")
    await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "Agent", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "No learned change is active yet" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "No learned procedure yet" }),
  ).toBeVisible();
  if (info.project.name === "mobile")
    await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "To review", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "No proposals to approve" }),
  ).toBeVisible();
  if (info.project.name === "mobile")
    await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "Connections", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "One mailbox, clear ownership" }),
  ).toBeVisible();
  if (info.project.name === "mobile")
    await expect(page.locator(".sidebar")).toBeHidden();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: `test-results/${info.project.name}-connections.png`,
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("protected endpoints reject foreign origins, invalid scope, and unconfigured services", async ({
  request,
}) => {
  const foreign = await request.post("/api/finance/commands", {
    headers: { origin: "https://foreign.invalid" },
    data: {},
  });
  expect(foreign.status()).toBe(403);
  const mailbox = await request.post("/api/connectors/gmail/start", {
    headers: { origin: "https://foreign.invalid" },
    data: {},
  });
  expect(mailbox.status()).toBe(403);
  const policyForeign = await request.post("/api/finance/approval-policy", {
    headers: { origin: "https://foreign.invalid" },
    data: {},
  });
  expect(policyForeign.status()).toBe(403);
  const policyInvalid = await request.post("/api/finance/approval-policy", {
    headers: { origin: "http://127.0.0.1:3317" },
    data: {
      organization_id: "d19587c6-6535-4455-b4cd-ea4819845ec1",
      run_id: "d19587c6-6535-4455-b4cd-ea4819845ec2",
      required_approvals: 3,
      expected_revision: 0,
    },
  });
  expect(policyInvalid.status()).toBe(400);
  const policyUnconfigured = await request.post(
    "/api/finance/approval-policy",
    {
      headers: { origin: "http://127.0.0.1:3317" },
      data: {
        organization_id: "d19587c6-6535-4455-b4cd-ea4819845ec1",
        run_id: "d19587c6-6535-4455-b4cd-ea4819845ec2",
        required_approvals: 1,
        expected_revision: 0,
      },
    },
  );
  expect(policyUnconfigured.status()).toBe(503);
  const localMutation = await request.post("/api/finance/demo", {
    headers: { origin: "http://127.0.0.1:3317" },
    data: { name: "No provider fixture" },
  });
  expect(localMutation.status()).toBe(503);
  const invalid = await request.get(
    "/api/finance/snapshot?organization_id=invalid&run_id=invalid",
  );
  expect(invalid.status()).toBe(400);
  const unconfigured = await request.get("/api/finance/scopes");
  expect(unconfigured.status()).toBe(503);
  expect(unconfigured.headers()["cache-control"]).toContain("no-store");
  const callback = await request.get("/auth/callback?code=invalid", {
    maxRedirects: 0,
  });
  expect(callback.headers().location).toBe(
    "http://127.0.0.1:3317/desk?auth_error=1",
  );
});

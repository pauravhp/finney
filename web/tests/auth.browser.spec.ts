import { expect, test, type Page } from "@playwright/test";

test.skip(
  !process.env.FINANCE_AUTH_BROWSER_FIXTURE,
  "Run npm run test:auth-browser for the isolated Supabase SDK fixture build.",
);

// Deliberately fake identities and responses. Never points at a hosted project,
// creates an actual account, sends email, or supplies a production session.
const authOrigin = "https://finance-auth.test.invalid";
const fixtureEmail = "member@example.test";
const fixturePassword = "Browser-only-fixture-928!";
// The SDK reads this exposed response header before accepting modern error codes.
const authHeaders = {
  "X-Supabase-Api-Version": "2024-01-01",
  "Access-Control-Expose-Headers": "X-Supabase-Api-Version",
};

async function enterCredentials(page: Page) {
  await page.getByLabel("Email address", { exact: true }).fill(fixtureEmail);
  await page.getByLabel("Password", { exact: true }).fill(fixturePassword);
}

test("a real SDK session response triggers a fresh authenticated-page navigation", async ({
  page,
}) => {
  let sessionReturned = false;
  const issuedAt = Math.floor(Date.now() / 1000);
  const fixtureUser = {
    id: "d19587c6-6535-4455-b4cd-ea4819845ec1",
    email: fixtureEmail,
    aud: "authenticated",
    role: "authenticated",
    created_at: "2026-10-25T00:00:00Z",
  };
  // Structurally valid fixture JWT, never a real token or a server-accepted identity.
  const encode = (value: unknown) =>
    Buffer.from(JSON.stringify(value)).toString("base64url");
  const accessToken = `${encode({ alg: "HS256", typ: "JWT" })}.${encode({ sub: fixtureUser.id, aud: "authenticated", role: "authenticated", iat: issuedAt, exp: issuedAt + 3600 })}.fixture-signature`;
  await page.route(`${authOrigin}/**`, async (route) => {
    const url = new URL(route.request().url());
    if (
      url.pathname === "/auth/v1/token" &&
      url.searchParams.get("grant_type") === "password"
    ) {
      sessionReturned = true;
      await route.fulfill({
        status: 200,
        headers: authHeaders,
        json: {
          access_token: accessToken,
          token_type: "bearer",
          expires_in: 3600,
          refresh_token: "test-only-refresh-fixture",
          user: fixtureUser,
        },
      });
    } else await route.abort();
  });
  await page.route("http://127.0.0.1:3317/desk", async (route) => {
    if (sessionReturned && route.request().isNavigationRequest())
      await route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<h1>Authenticated navigation fixture</h1>",
      });
    else await route.continue();
  });
  await page.goto("/desk");
  await enterCredentials(page);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Authenticated navigation fixture" }),
  ).toBeVisible();
  const cookies = await page.context().cookies();
  expect(
    cookies.some(
      (cookie) =>
        cookie.name.startsWith("sb-") && cookie.name.includes("auth-token"),
    ),
  ).toBe(true);
});

test("email sign-in uses the SDK password grant and contains credential errors", async ({
  page,
}, info) => {
  const errors: string[] = [];
  const leaks: string[] = [];
  let passwordGrant = false;
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (request.url().includes(fixturePassword))
      leaks.push("credential in URL");
    if (
      !request.url().startsWith(authOrigin) &&
      request.postData()?.includes(fixturePassword)
    )
      leaks.push("credential outside Supabase Auth");
  });
  await page.route(`${authOrigin}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (
      url.pathname === "/auth/v1/token" &&
      url.searchParams.get("grant_type") === "password"
    ) {
      const body = request.postDataJSON();
      passwordGrant =
        body.email === fixtureEmail && body.password === fixturePassword;
      await route.fulfill({
        status: 400,
        headers: authHeaders,
        json: {
          code: "invalid_credentials",
          msg: "Private upstream detail must not render",
        },
      });
    } else await route.abort();
  });
  await page.goto("/desk");
  await expect(
    page.getByRole("heading", { name: "Your event. Your team's decisions." }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Continue with Google" }),
  ).toHaveCount(0);
  await expect(page.locator(".auth-form")).toHaveAttribute("method", "post");
  await enterCredentials(page);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.locator(".signin-panel").getByRole("alert")).toContainText(
    "The email or password was not accepted",
  );
  await expect(
    page.getByText("Private upstream detail must not render"),
  ).toHaveCount(0);
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeEnabled();
  expect(passwordGrant).toBe(true);
  expect(leaks).toEqual([]);
  const persistedPassword = await page.evaluate((password) => {
    return (
      document.cookie.includes(password) ||
      JSON.stringify(localStorage).includes(password) ||
      JSON.stringify(sessionStorage).includes(password)
    );
  }, fixturePassword);
  expect(persistedPassword).toBe(false);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: `test-results/${info.project.name}-email-signin.png`,
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("signup with no session stays pending confirmation and cannot open finance records", async ({
  page,
}, info) => {
  let signupRequest = false;
  let financeRequests = 0;
  page.on("request", (request) => {
    if (request.url().includes("/api/finance/")) financeRequests++;
  });
  await page.route(`${authOrigin}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/auth/v1/signup") {
      const body = request.postDataJSON();
      signupRequest =
        body.email === fixtureEmail &&
        body.password === fixturePassword &&
        typeof body.code_challenge === "string" &&
        url.searchParams.get("redirect_to") ===
          "http://127.0.0.1:3317/auth/callback";
      await route.fulfill({
        status: 200,
        json: {
          id: "d19587c6-6535-4455-b4cd-ea4819845ec1",
          email: fixtureEmail,
          aud: "authenticated",
          role: "authenticated",
          created_at: "2026-10-25T00:00:00Z",
          identities: [],
        },
      });
    } else await route.abort();
  });
  await page.goto("/desk");
  await page
    .getByRole("button", { name: "New here? Create an account" })
    .click();
  await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute(
    "autocomplete",
    "new-password",
  );
  await enterCredentials(page);
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Check your email to continue" }),
  ).toBeVisible();
  await expect(page.getByRole("status")).toContainText(
    "Open it in this browser",
  );
  await expect(
    page.getByRole("button", { name: "Create my demo run" }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Password", { exact: true })).toHaveCount(0);
  expect(signupRequest).toBe(true);
  expect(financeRequests).toBe(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: `test-results/${info.project.name}-email-confirmation.png`,
    fullPage: true,
  });
  await page.getByRole("button", { name: "Back to sign in" }).click();
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("Email address", { exact: true })).toHaveValue(
    fixtureEmail,
  );
});

test("unconfirmed account and failed callback give an actionable next step", async ({
  page,
}) => {
  await page.route(`${authOrigin}/**`, async (route) => {
    await route.fulfill({
      status: 400,
      headers: authHeaders,
      json: { code: "email_not_confirmed", msg: "Email not confirmed" },
    });
  });
  await page.goto("/desk?auth_error=1");
  await expect(page.locator(".signin-panel").getByRole("alert")).toContainText(
    "confirmation link could not finish",
  );
  await enterCredentials(page);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.locator(".signin-panel").getByRole("alert")).toContainText(
    "Confirm your email before signing in",
  );
  await expect(
    page.getByRole("button", { name: "Create my demo run" }),
  ).toHaveCount(0);
});

test("email delivery restrictions remain recoverable without claiming an account was created", async ({
  page,
}) => {
  await page.route(`${authOrigin}/**`, async (route) => {
    await route.fulfill({
      status: 429,
      headers: authHeaders,
      json: { code: "over_email_send_rate_limit", msg: "Rate limit exceeded" },
    });
  });
  await page.goto("/desk");
  await page
    .getByRole("button", { name: "New here? Create an account" })
    .click();
  await enterCredentials(page);
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(page.locator(".signin-panel").getByRole("alert")).toContainText("Wait a few minutes");
  await expect(
    page.getByRole("button", { name: "Create account", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("heading", { name: "Check your email to continue" }),
  ).toHaveCount(0);
});

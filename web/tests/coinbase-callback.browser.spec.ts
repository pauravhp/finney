import { test, expect } from "@playwright/test";

const path = "/oauth/coinbase/callback";
const params = new URLSearchParams({
  code: "fixture-code-not-a-real-grant",
  state: "a".repeat(43),
});

test("hosted handoff clears address bar, keeps code private and makes no network calls", async ({
  page,
}, testInfo) => {
  const requests: string[] = [];
  const errors: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  page.on("pageerror", (error) => errors.push(error.message));
  const response = await page.goto(`${path}?${params}`);
  expect(response?.headers()["cache-control"]).toContain("no-store");
  expect(response?.headers()["referrer-policy"]).toBe("no-referrer");
  expect(response?.headers()["content-security-policy"]).toContain(
    "default-src 'none'",
  );
  await expect(page).toHaveURL(new RegExp(`${path}$`));
  await expect(
    page.getByRole("heading", { name: "Finish connecting Coinbase" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Copy secure callback" }),
  ).toBeVisible();
  expect(await page.locator("#callback").inputValue()).toContain(
    params.toString(),
  );
  expect(await page.locator("#callback").isVisible()).toBe(false);
  expect(requests).toHaveLength(1);
  expect(errors).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: `.impeccable/review/${testInfo.project.name}.png`,
    fullPage: true,
  });
  await page.getByText("Show callback for manual copying").click();
  await expect(
    page.getByLabel("Temporary callback — keep private"),
  ).toBeVisible();
});

test("missing, denied and duplicate callbacks never claim a wallet connection", async ({
  page,
}) => {
  for (const query of [
    "",
    "?error=access_denied",
    `?${params}&code=duplicate`,
  ]) {
    await page.goto(path + query);
    await expect(page).toHaveURL(new RegExp(`${path}$`));
    await expect(
      page.getByRole("heading", { name: "Coinbase connection not completed" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Copy secure callback" }),
    ).toBeHidden();
  }
});

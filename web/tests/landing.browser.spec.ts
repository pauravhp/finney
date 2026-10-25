import { expect, test } from "@playwright/test";

test("standalone v7 landing keeps its original design and opens the real desk", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", {
      name: "The finance teammate for hackathon organizers.",
    }),
  ).toBeVisible();
  await expect(page.locator(".marketing-root")).toHaveCount(0);
  expect(await page.evaluate(() => getComputedStyle(document.body).fontFamily)).toContain("Albert Sans");
  expect(await page.locator('link[href*="/_next/"]').count()).toBe(0);
  await page.screenshot({
    path: `test-results/${info.project.name}-landing.png`,
  });
  await page.getByRole("button", { name: "Spending", exact: true }).click();
  await expect(page.locator('[data-folder="Spending"]')).toHaveClass(/front/);
  await page
    .getByRole("button", { name: "How it works", exact: false })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Close", exact: true }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
  await page
    .getByRole("button", { name: "Try Finney", exact: false })
    .first()
    .click();
  await expect(page).toHaveURL(/\/desk\?demo=guided$/);
  await expect(
    page.getByRole("heading", { name: /Connect your event to begin|Sign in to Finney/ }),
  ).toBeVisible();
});


test("prototype view/state URLs cannot open the scripted desk; legacy app links survive", async ({page}) => {
  await page.goto("/?view=desk&state=complete");
  await expect(page.locator(".hero h1")).toBeVisible();
  await expect(page.locator(".desk-sidebar")).toHaveCount(0);
  await page.getByRole("button", {name:"Open report",exact:false}).click();
  await expect(page).toHaveURL(/\/desk\?demo=guided&section=reports$/);
  await page.goto("/?signin=1");
  await expect(page).toHaveURL(/\/desk$/);
});

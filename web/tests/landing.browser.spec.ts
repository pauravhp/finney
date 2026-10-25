import { expect, test } from "@playwright/test";

test("approved landing opens the live desk and labels the illustrated learning example", async ({
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
  await expect(
    page.getByText("Illustrative financial examples below.", { exact: false }),
  ).toBeVisible();
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
    .getByRole("link", { name: "Try Finney", exact: false })
    .first()
    .click();
  await expect(page).toHaveURL(/\/desk$/);
  await expect(
    page.getByRole("heading", { name: "Work", exact: true }),
  ).toBeVisible();
});

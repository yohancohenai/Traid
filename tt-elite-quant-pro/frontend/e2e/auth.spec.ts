import { expect, test } from "@playwright/test";

test.describe("login", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("redirects to /login and signs in", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/login/);
    await page.getByLabel("Username").fill("admin");
    await page.getByLabel("Password").fill("change-me");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: "OVERVIEW" })).toBeVisible();
    const token = await page.evaluate(() => localStorage.getItem("ttq.token"));
    expect(token).toBeTruthy();
  });
});

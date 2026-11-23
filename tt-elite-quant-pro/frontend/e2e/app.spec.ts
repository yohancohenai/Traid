import { expect, test } from "@playwright/test";
import { NAV_PATHS, confirmBetModal, ensureDemo, trackErrors, waitForOpportunities } from "./helpers";

test("DEMO banner is visible in demo mode and hidden in LIVE", async ({ page }) => {
  await page.goto("/");
  await ensureDemo(page);
  await expect(page.getByTestId("demo-banner")).toHaveText("DEMO MODE — synthetic data. Not real matches, odds or results.");
  await page.getByTestId("mode-live").click();
  await expect(page.getByTestId("demo-banner")).toHaveCount(0);
  await page.getByTestId("mode-demo").click();
  await expect(page.getByTestId("demo-banner")).toBeVisible();
  // disclaimer from /api/meta in the footer
  await expect(page.getByTestId("disclaimer")).toContainText("Research tool only");
});

test("opportunities render items or NO QUALIFYING BETS FOUND.", async ({ page }) => {
  await page.goto("/opportunities");
  await ensureDemo(page);
  await waitForOpportunities(page);
  const cards = await page.getByTestId("opportunity-card").count();
  if (cards === 0) await expect(page.getByTestId("no-qualifying")).toContainText("NO QUALIFYING BETS FOUND.");
  else {
    const first = page.getByTestId("opportunity-card").first();
    await expect(first).toContainText("Hard Rock Bet");
    await expect(first).toContainText("Estimated EV");
    await expect(first.getByTestId("demo-badge").first()).toBeVisible();
  }
});

test("DraftKings is reference-only on the odds page", async ({ page }) => {
  await page.goto("/odds");
  await ensureDemo(page);
  await page.getByTestId("odds-link").first().click();
  const dk = page.getByTestId("book-draftkings");
  await expect(dk).toBeVisible();
  await expect(dk).toContainText("Reference only — not executable in Florida");
  await expect(dk.getByRole("button", { name: /bet/i })).toHaveCount(0);
  await expect(page.getByTestId("book-hardrock")).toContainText("Executable in Florida");
});

test("BET PLACED records a bet on a DEMO opportunity and it shows in My Bets as PLACED", async ({ page }) => {
  await page.goto("/opportunities");
  await ensureDemo(page);
  await waitForOpportunities(page);
  const enabled = page.getByTestId("opportunity-card").filter({ has: page.locator('[data-testid="btn-bet-placed"]:enabled') });
  const n = await enabled.count();
  test.skip(n === 0, "no DEMO opportunities available to bet on");
  const card = enabled.nth(Math.floor(Math.random() * Math.min(n, 20)));
  await expect(card.getByTestId("demo-badge").first()).toBeVisible();
  await card.getByTestId("btn-bet-placed").click();

  const modal = page.getByTestId("bet-modal");
  await expect(modal).toBeVisible();
  await expect(modal).toContainText("Enter the odds Hard Rock actually accepted, not the recommended price.");
  await modal.getByTestId("bet-odds").fill("+120");
  await expect(modal.getByTestId("bet-decimal")).toContainText("2.200");
  await modal.getByTestId("bet-stake").fill("5");
  await expect(modal.getByTestId("bet-payout")).toContainText("$11.00");
  const betId = await confirmBetModal(modal);
  expect(betId).toBeTruthy();
  await modal.getByRole("button", { name: "Close" }).last().click();

  await page.goto("/bets");
  const row = page.locator(`[data-testid="bet-row"][data-bet-id="${betId}"]`);
  await expect(row).toBeVisible();
  await expect(row.getByTestId("bet-status")).toHaveText("PLACED");
  await expect(row.getByTestId("demo-badge")).toBeVisible();
});

test("SKIP BET marks an opportunity skipped", async ({ page }) => {
  await page.goto("/opportunities");
  await ensureDemo(page);
  await waitForOpportunities(page);
  const skippable = page.getByTestId("opportunity-card").filter({ has: page.locator('[data-testid="btn-skip"]:enabled') });
  const n = await skippable.count();
  test.skip(n === 0, "no skippable opportunities");
  const card = skippable.first();
  const title = (await card.locator("h3").textContent()) || "";
  const skipResp = page.waitForResponse((r) => /\/api\/opportunities\/\d+\/skip/.test(r.url()) && r.request().method() === "POST");
  await card.getByTestId("btn-skip").click();
  expect((await skipResp).status()).toBe(200);
  await expect(page.getByTestId("opportunity-card").filter({ hasText: title }).first().getByTestId("btn-skip")).toHaveText("SKIPPED");
});

test("every nav page loads without console errors", async ({ page }) => {
  const errors = trackErrors(page);
  await page.goto("/");
  await ensureDemo(page);
  for (const p of NAV_PATHS) {
    await page.goto(p);
    await expect(page.locator("main h1").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expect(page.locator('main [role="alert"]')).toHaveCount(0);
  }
  // detail pages
  await page.goto("/matches");
  await page.getByTestId("match-row").first().click();
  await expect(page.getByText("Scoreline distribution (P1 perspective)")).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.goto("/players");
  await page.locator("main table a").first().click();
  await expect(page.getByText("Rating history (Elo · Glicko-2 · Bayes)")).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(errors, errors.join("\n")).toEqual([]);
});

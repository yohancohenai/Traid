import { expect, test } from "@playwright/test";
import { confirmBetModal, ensureDemo } from "./helpers";

test("match analyzer computes probability and Estimated EV", async ({ page }) => {
  await page.goto("/analyzer");
  await ensureDemo(page);
  const p1 = page.getByTestId("analyzer-p1");
  await p1.click();
  await page.getByRole("option").first().click();
  const p2 = page.getByTestId("analyzer-p2");
  await p2.click();
  await page.getByRole("option").nth(1).click();
  await page.getByPlaceholder("-150").fill("-150");
  await page.getByPlaceholder("+125").fill("+125");
  await page.getByRole("button", { name: "Analyze" }).click();
  await expect(page.getByText("Component & rating-engine probabilities (P1)")).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText("Overround", { exact: true })).toBeVisible();
  await expect(page.getByText(/Estimated EV sensitivity/).first()).toBeVisible();
});

test("manual bet entry with match picker and educational stake simulation", async ({ page }) => {
  await page.goto("/bets");
  await ensureDemo(page);
  await page.getByTestId("record-manual").click();
  const modal = page.getByTestId("bet-modal");
  const sel = modal.getByTestId("bet-match");
  await expect(sel.locator("option").nth(1)).toBeAttached();
  await sel.selectOption({ index: 1 });
  await modal.getByTestId("bet-selection").selectOption("p2");
  await modal.getByTestId("bet-odds").fill("-110");
  await modal.getByTestId("bet-stake").fill("3");
  await modal.getByRole("button", { name: "Show stake simulation" }).click();
  await expect(modal.getByText("Educational stake simulation only")).toBeVisible();
  await modal.getByPlaceholder("55").fill("55");
  await modal.getByRole("button", { name: "Simulate" }).click();
  await expect(modal.getByText(/Fractional Kelly/)).toBeVisible();
  await confirmBetModal(modal);
  await expect(modal.getByTestId("bet-recorded")).toContainText("PLACED");
});

test("bet correction requires a reason and appears in audit history", async ({ page }) => {
  await page.goto("/bets");
  await ensureDemo(page);
  // earlier specs record DEMO bets, so at least one row exists
  const row = page.getByTestId("bet-row").first();
  await expect(row).toBeVisible();
  await row.click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByText("Correct bet")).toBeVisible();
  const note = `e2e correction ${Date.now()}`;
  await drawer.getByLabel("Notes").fill(note);
  await drawer.getByLabel("Reason for correction (required)").fill("e2e test correction");
  await drawer.getByRole("button", { name: "Save correction" }).click();
  await expect(drawer.getByText("Correction saved")).toBeVisible();
  await expect(drawer.getByText("“e2e test correction”").first()).toBeVisible();
});

test("fast manual Hard Rock entry stores quotes", async ({ page }) => {
  await page.goto("/odds");
  await ensureDemo(page);
  const card = page.getByTestId("manual-entry");
  const sel = card.getByTestId("manual-match");
  await expect(sel.locator("option").nth(1)).toBeAttached();
  await sel.selectOption({ index: 1 });
  await card.getByTestId("manual-p1").fill("+130");
  await card.getByTestId("manual-p2").fill("-160");
  await card.getByRole("button", { name: "Store Hard Rock quotes" }).click();
  await expect(card.getByTestId("manual-result")).toContainText("VERIFIED");
});

test("CSV export downloads with auth", async ({ page }) => {
  await page.goto("/bets");
  await ensureDemo(page);
  const dl = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const d = await dl;
  expect(d.suggestedFilename()).toBe("ttq_bets_demo.csv");
});

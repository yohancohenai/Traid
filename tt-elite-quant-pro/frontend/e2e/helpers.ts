import { expect, type Locator, type Page } from "@playwright/test";

export const NAV_PATHS = ["/", "/matches", "/opportunities", "/live", "/players", "/analyzer", "/odds", "/bets", "/bankroll", "/backtests", "/models", "/sources", "/settings"];

/** Collect console errors and uncaught page errors. */
export function trackErrors(page: Page) {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`console: ${m.text()}`);
  });
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  return errors;
}

export async function ensureDemo(page: Page) {
  await expect(page.getByTestId("mode-demo")).toBeVisible();
  if ((await page.getByTestId("mode-demo").getAttribute("aria-pressed")) !== "true") await page.getByTestId("mode-demo").click();
  await expect(page.getByTestId("demo-banner")).toBeVisible();
}

/** Wait for the opportunities page to finish loading (cards or the empty state). */
export async function waitForOpportunities(page: Page) {
  await expect(page.getByTestId("opportunity-card").first().or(page.getByTestId("no-qualifying")).first()).toBeVisible({ timeout: 30_000 });
}

/** Submit the BET PLACED modal, answering the duplicate (409) and risk-limit (422) prompts if they appear. */
export async function confirmBetModal(modal: Locator) {
  await modal.getByTestId("bet-submit").click();
  const recorded = modal.getByTestId("bet-recorded");
  const separate = modal.getByRole("button", { name: "This is a separate bet" });
  const anyway = modal.getByRole("button", { name: "Record anyway" });
  for (let i = 0; i < 4; i++) {
    await expect(recorded.or(separate).or(anyway)).toBeVisible();
    if (await recorded.isVisible()) break;
    const btn = (await separate.isVisible()) ? separate : anyway;
    await btn.click();
    await expect(btn).toBeHidden();
  }
  await expect(recorded).toBeVisible();
  const text = (await recorded.textContent()) || "";
  return text.match(/Bet #(\d+)/)?.[1] || null;
}

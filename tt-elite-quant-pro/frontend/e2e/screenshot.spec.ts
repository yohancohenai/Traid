import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, test } from "@playwright/test";

/** Upload a SYNTHETIC Hard Rock-style list screenshot (rendered from upcoming DEMO matches), confirm, save. */
test("Hard Rock screenshot import proposes prices and saves only confirmed rows", async ({ page, request }) => {
  const api = process.env.E2E_API_URL || "http://localhost:8000";
  const state = JSON.parse(fs.readFileSync(path.join(__dirname, ".auth", "state.json"), "utf8"));
  const token = state.origins[0].localStorage.find((x: { name: string }) => x.name === "ttq.token").value;
  const res = await request.get(`${api}/api/matches?demo=true&status=SCHEDULED&days_back=0&days_ahead=1`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const upcoming = ((await res.json()) as { player1: { name: string }; player2: { name: string }; scheduled_at: string }[])
    .filter((m) => new Date(m.scheduled_at).getTime() > Date.now() + 10 * 60_000)
    .slice(0, 2);
  test.skip(upcoming.length < 2, "needs two upcoming DEMO matches");
  const png = path.join(os.tmpdir(), `hr-${Date.now()}.png`);
  const rows = [
    [upcoming[0].player1.name, "-150", upcoming[0].player2.name, "+120"],
    [upcoming[1].player1.name, "-185", upcoming[1].player2.name, "+145"],
  ];
  execFileSync("python3", [path.join(__dirname, "../../backend/tests/fixtures/hardrock/make_synthetic.py"), JSON.stringify(rows), png]);

  await page.goto("/odds");
  await page.getByTestId("hr-screenshot-file").setInputFiles(png);
  await expect(page.getByTestId("hr-proposal")).toHaveCount(2, { timeout: 30_000 });
  await expect(page.getByTestId("hr-proposal").first()).toContainText(upcoming[0].player1.name.split(" ").pop()!);
  // Ensure both rows are selected (OCR confidence flags may leave a row unchecked for review)
  for (const box of await page.getByLabel("use row").all()) await box.check();
  await page.getByTestId("hr-save").click();
  await expect(page.getByTestId("hr-screenshot")).toContainText("Saved 2 match prices", { timeout: 30_000 });
  fs.unlinkSync(png);
});

import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";

const PREINSTALLED = "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome";
const executablePath = process.env.PW_CHROMIUM_PATH || (fs.existsSync(PREINSTALLED) ? PREINSTALLED : undefined);

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:3000",
    storageState: "e2e/.auth/state.json",
    trace: "off",
    viewport: { width: 1440, height: 900 },
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 }, launchOptions: executablePath ? { executablePath } : {} },
    },
  ],
  // The app is expected to be started separately (npm run build && npm start).
  // Set E2E_WEB_SERVER=1 to let Playwright start it.
  webServer: process.env.E2E_WEB_SERVER
    ? { command: "npm run start", url: "http://localhost:3000", reuseExistingServer: true, timeout: 120_000 }
    : undefined,
});

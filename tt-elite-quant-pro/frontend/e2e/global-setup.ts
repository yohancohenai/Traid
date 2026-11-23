import fs from "node:fs";
import path from "node:path";
import type { FullConfig } from "@playwright/test";

/** Log in once through the API (the backend rate-limits logins) and seed localStorage with token + DEMO mode. */
export default async function globalSetup(config: FullConfig) {
  const api = process.env.E2E_API_URL || "http://localhost:8000";
  const baseURL = (config.projects[0].use.baseURL as string) || "http://localhost:3000";
  const res = await fetch(`${api}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: process.env.E2E_USER || "admin", password: process.env.E2E_PASS || "change-me" }),
  });
  if (!res.ok) throw new Error(`login failed: ${res.status} ${await res.text()}`);
  const { access_token } = (await res.json()) as { access_token: string };
  const origin = new URL(baseURL).origin;
  const state = {
    cookies: [],
    origins: [
      {
        origin,
        localStorage: [
          { name: "ttq.token", value: access_token },
          { name: "ttq.dataMode", value: "DEMO" },
        ],
      },
    ],
  };
  const out = path.join(__dirname, ".auth", "state.json");
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, JSON.stringify(state, null, 2));
}

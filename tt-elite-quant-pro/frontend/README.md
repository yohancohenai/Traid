# TT Elite Quant Pro — frontend

Next.js (App Router) + TypeScript + Tailwind CSS + Recharts client for the FastAPI backend in `../backend`.
All data is fetched client-side from `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`) with a bearer token
kept in `localStorage`; a 401 sends you to `/login`.

## Run

```bash
cp .env.example .env.local        # optional; edit NEXT_PUBLIC_API_URL
npm ci
npm run dev                       # http://localhost:3000
# production
npm run build && npm start        # port 3000
```

Checks: `npm run typecheck`, `npm run lint`, `npm run build`.

## End-to-end tests (Playwright)

The app and backend must already be running (`npm run build && npm start`, backend on :8000).

```bash
npx playwright test --trace off   # or: npm run test:e2e
```

`e2e/global-setup.ts` logs in once through the API (the backend rate-limits logins) and stores the token and
`DEMO` data mode in `e2e/.auth/state.json`. Tests record and skip bets on DEMO data only. Set `PW_CHROMIUM_PATH`
to use a specific Chromium build; `/opt/pw-browsers/chromium-1243` is used automatically when present.
`E2E_WEB_SERVER=1` lets Playwright start `npm start` itself.

## Docker

```bash
docker build --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 -t ttq-frontend .
docker run -p 3000:3000 ttq-frontend
```

The image uses Next.js standalone output (`NEXT_OUTPUT=standalone` is set in the build stage).

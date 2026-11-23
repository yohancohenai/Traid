"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";
import { getToken, setToken } from "@/lib/api";
import { AppProvider, useApp } from "@/lib/app-context";
import { AlertsBell } from "./alerts-bell";
import { cx } from "./ui";

export const NAV = [
  { href: "/", label: "Overview" },
  { href: "/matches", label: "Upcoming Matches" },
  { href: "/opportunities", label: "Bet Opportunities" },
  { href: "/live", label: "Live Matches" },
  { href: "/players", label: "Player Ratings" },
  { href: "/analyzer", label: "Match Analyzer" },
  { href: "/odds", label: "Odds Comparison" },
  { href: "/bets", label: "My Bets" },
  { href: "/bankroll", label: "Bankroll" },
  { href: "/backtests", label: "Backtesting" },
  { href: "/models", label: "Model Performance" },
  { href: "/sources", label: "Data Sources" },
  { href: "/settings", label: "Settings" },
];

function isActive(path: string, href: string) {
  return href === "/" ? path === "/" : path === href || path.startsWith(href + "/");
}

const noopSubscribe = () => () => undefined;

export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const isLogin = path === "/login";
  // null on the server, token presence on the client
  const authed = useSyncExternalStore(
    noopSubscribe,
    () => !!getToken(),
    () => null,
  );

  useEffect(() => {
    if (!isLogin && authed === false) router.replace(`/login?next=${encodeURIComponent(path)}`);
  }, [isLogin, authed, path, router]);

  if (isLogin) return <>{children}</>;
  if (!authed) return <div className="p-8 text-center text-xs text-sub">Checking session…</div>;
  return (
    <AppProvider>
      <Frame>{children}</Frame>
    </AppProvider>
  );
}

function ModeToggle() {
  const { demo, setDemo, health } = useApp();
  return (
    <div className="flex items-center gap-1.5" title={`Live matches in DB: ${health?.live_matches_in_db ?? "?"} · Demo matches: ${health?.demo_matches_in_db ?? "?"}`}>
      <span className="hidden text-[10px] font-semibold uppercase tracking-wider text-dim sm:inline">Data mode</span>
      <div className="inline-flex overflow-hidden rounded-md border border-line2" role="group" aria-label="Data mode">
        <button
          data-testid="mode-live"
          aria-pressed={!demo}
          onClick={() => setDemo(false)}
          className={cx("px-2.5 py-1 text-[11px] font-bold tracking-wider", !demo ? "bg-sky-500/20 text-sky-300" : "text-sub hover:text-ink")}
        >
          LIVE
        </button>
        <button
          data-testid="mode-demo"
          aria-pressed={demo}
          onClick={() => setDemo(true)}
          className={cx("px-2.5 py-1 text-[11px] font-bold tracking-wider", demo ? "bg-amber-500/20 text-amber-300" : "text-sub hover:text-ink")}
        >
          DEMO
        </button>
      </div>
    </div>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  const { ready, demo, meta, health } = useApp();
  const path = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);

  const logout = () => {
    setToken(null);
    router.replace("/login");
  };

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      {/* sidebar (desktop) */}
      <aside className="hidden w-56 shrink-0 border-r border-line bg-panel lg:flex lg:flex-col">
        <div className="border-b border-line px-4 py-3.5">
          <Link href="/" className="block">
            <div className="text-[13px] font-bold tracking-[0.14em] text-ink">TT ELITE</div>
            <div className="text-[10px] font-semibold tracking-[0.22em] text-accent">QUANT PRO</div>
          </Link>
        </div>
        <nav className="flex-1 overflow-y-auto py-2" aria-label="Main">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className={cx(
                "block border-l-2 px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wider",
                isActive(path, n.href) ? "border-accent bg-sky-500/5 text-ink" : "border-transparent text-sub hover:text-ink",
              )}
            >
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="border-t border-line px-4 py-2 text-[10px] text-dim">
          API {health?.status ?? "…"} · DB {health?.db ?? "…"} · v{health?.version ?? "?"}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 border-b border-line bg-bg/95 backdrop-blur">
          <div className="flex items-center justify-between gap-2 px-3 py-2 lg:px-5">
            <div className="flex items-center gap-2 lg:hidden">
              <button className="btn btn-ghost px-2" aria-label="Menu" aria-expanded={menuOpen} onClick={() => setMenuOpen((o) => !o)}>
                ☰
              </button>
              <Link href="/" className="text-[12px] font-bold tracking-[0.12em]">
                TT ELITE <span className="text-accent">QUANT PRO</span>
              </Link>
            </div>
            <div className="hidden text-[11px] text-dim lg:block">
              {meta ? `${meta.primary_book} · ${meta.region} · times in ${meta.timezone}` : ""}
            </div>
            <div className="flex items-center gap-2">
              <ModeToggle />
              <AlertsBell />
              <button className="btn btn-ghost hidden sm:inline-flex" onClick={logout}>
                Sign out
              </button>
            </div>
          </div>
          {menuOpen && (
            <nav className="grid grid-cols-2 gap-1 border-t border-line bg-panel p-2 sm:grid-cols-3 lg:hidden" aria-label="Main mobile">
              {NAV.map((n) => (
                <Link
                  key={n.href}
                  href={n.href}
                  onClick={() => setMenuOpen(false)}
                  className={cx("rounded px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wider", isActive(path, n.href) ? "bg-sky-500/10 text-ink" : "text-sub")}
                >
                  {n.label}
                </Link>
              ))}
              <button className="rounded px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wider text-sub" onClick={logout}>
                Sign out
              </button>
            </nav>
          )}
          {demo && (
            <div data-testid="demo-banner" role="status" className="border-t border-amber-500/40 bg-amber-500/15 px-3 py-1.5 text-center text-[12px] font-semibold tracking-wide text-amber-300">
              DEMO MODE — synthetic data. Not real matches, odds or results.
            </div>
          )}
        </header>

        <main className="min-w-0 flex-1 px-3 py-4 lg:px-5">{ready ? children : <div className="p-8 text-center text-xs text-sub">Loading…</div>}</main>

        <footer className="border-t border-line px-3 py-3 text-[11px] leading-relaxed text-dim lg:px-5" data-testid="disclaimer">
          {meta?.disclaimer ?? "Research tool only."}
        </footer>
      </div>
    </div>
  );
}

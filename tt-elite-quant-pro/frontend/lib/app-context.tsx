"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";
import type { Health, Meta } from "./types";

const MODE_KEY = "ttq.dataMode";

interface AppState {
  meta: Meta | null;
  health: Health | null;
  demo: boolean;
  tz: string;
  ready: boolean;
  setDemo: (d: boolean) => void;
  refreshHealth: () => void;
}

const Ctx = createContext<AppState | null>(null);

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp outside AppProvider");
  return v;
}

function readMode(): "DEMO" | "LIVE" | null {
  try {
    const v = window.localStorage.getItem(MODE_KEY);
    return v === "DEMO" || v === "LIVE" ? v : null;
  } catch {
    return null;
  }
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [demo, setDemoState] = useState(true);
  const [ready, setReady] = useState(false);

  const refreshHealth = useCallback(() => {
    api<Health>("/api/health").then(setHealth).catch(() => undefined);
  }, []);

  useEffect(() => {
    let alive = true;
    Promise.allSettled([api<Meta>("/api/meta"), api<Health>("/api/health")]).then(([m, h]) => {
      if (!alive) return;
      if (m.status === "fulfilled") setMeta(m.value);
      const hv = h.status === "fulfilled" ? h.value : null;
      setHealth(hv);
      const stored = readMode();
      if (stored) setDemoState(stored === "DEMO");
      else setDemoState(!hv || !hv.live_matches_in_db);
      setReady(true);
    });
    return () => {
      alive = false;
    };
  }, []);

  const setDemo = useCallback((d: boolean) => {
    setDemoState(d);
    try {
      window.localStorage.setItem(MODE_KEY, d ? "DEMO" : "LIVE");
    } catch {
      /* ignore */
    }
  }, []);

  return (
    <Ctx.Provider value={{ meta, health, demo, tz: meta?.timezone || "America/New_York", ready, setDemo, refreshHealth }}>
      {children}
    </Ctx.Provider>
  );
}

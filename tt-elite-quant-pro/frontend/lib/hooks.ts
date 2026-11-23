"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api";

type Query = Record<string, string | number | boolean | null | undefined>;

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  status: number | null;
  loading: boolean;
  reload: () => void;
}

interface Snap<T> {
  key: string | null;
  data: T | null;
  error: string | null;
  status: number | null;
}

/** GET an endpoint; refetches when path/query change. Pass path=null to skip. */
export function useApi<T>(path: string | null, query?: Query, opts: { intervalMs?: number } = {}): ApiState<T> {
  const key = path ? path + "?" + JSON.stringify(query || {}) : null;
  const [snap, setSnap] = useState<Snap<T>>({ key: null, data: null, error: null, status: null });
  const [refreshing, setRefreshing] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!path) return;
    const ctrl = new AbortController();
    api<T>(path, { query, signal: ctrl.signal })
      .then((d) => setSnap({ key, data: d, error: null, status: 200 }))
      .catch((e: unknown) => {
        if ((e as Error).name === "AbortError") return;
        setSnap((prev) => ({
          key,
          data: prev.key === key ? prev.data : null,
          error: (e as Error).message || "Request failed",
          status: e instanceof ApiError ? e.status : null,
        }));
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setRefreshing(false);
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tick]);

  useEffect(() => {
    if (!opts.intervalMs || !path) return;
    const t = setInterval(() => setTick((x) => x + 1), opts.intervalMs);
    return () => clearInterval(t);
  }, [opts.intervalMs, path]);

  const reload = useCallback(() => {
    setRefreshing(true);
    setTick((x) => x + 1);
  }, []);

  const current = snap.key === key;
  return {
    data: current ? snap.data : null,
    error: current ? snap.error : null,
    status: current ? snap.status : null,
    loading: !!path && (!current || refreshing),
    reload,
  };
}

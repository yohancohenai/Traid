"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";

type Query = Record<string, string | number | boolean | null | undefined>;

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  status: number | null;
  loading: boolean;
  reload: () => void;
}

/** GET an endpoint; refetches when path/query change. Pass path=null to skip. */
export function useApi<T>(path: string | null, query?: Query, opts: { intervalMs?: number } = {}): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<number | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const [tick, setTick] = useState(0);
  const key = path ? path + "?" + JSON.stringify(query || {}) : null;
  const lastKey = useRef<string | null>(null);

  useEffect(() => {
    if (!path) {
      setLoading(false);
      return;
    }
    const ctrl = new AbortController();
    if (lastKey.current !== key) setData(null);
    lastKey.current = key;
    setLoading(true);
    api<T>(path, { query, signal: ctrl.signal })
      .then((d) => {
        setData(d);
        setError(null);
        setStatus(200);
      })
      .catch((e: unknown) => {
        if ((e as Error).name === "AbortError") return;
        setError((e as Error).message || "Request failed");
        setStatus(e instanceof ApiError ? e.status : null);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tick]);

  useEffect(() => {
    if (!opts.intervalMs || !path) return;
    const t = setInterval(() => setTick((x) => x + 1), opts.intervalMs);
    return () => clearInterval(t);
  }, [opts.intervalMs, path]);

  const reload = useCallback(() => setTick((x) => x + 1), []);
  return { data, error, status, loading, reload };
}

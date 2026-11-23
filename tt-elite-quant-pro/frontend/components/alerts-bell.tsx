"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Alert } from "@/lib/types";
import { Badge, DemoBadge, Time, cx } from "./ui";

export function AlertsBell() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [open, setOpen] = useState(false);
  const [perm, setPerm] = useState<string>("default");
  const seen = useRef<Set<number> | null>(null);
  const box = useRef<HTMLDivElement>(null);

  const poll = useCallback(async () => {
    try {
      const a = await api<Alert[]>("/api/alerts", { query: { unread: true, limit: 50 } });
      setAlerts(a);
      if (seen.current === null) {
        seen.current = new Set(a.map((x) => x.id));
        return;
      }
      const fresh = a.filter((x) => !seen.current!.has(x.id));
      fresh.forEach((x) => seen.current!.add(x.id));
      if (fresh.length && typeof Notification !== "undefined" && Notification.permission === "granted") {
        for (const x of fresh.slice(0, 3)) {
          try {
            new Notification(`${x.is_demo ? "[DEMO] " : ""}${x.title}`, { body: x.body, tag: `ttq-${x.id}` });
          } catch {
            /* notifications unsupported in this context */
          }
        }
      }
    } catch {
      /* polling errors are non-fatal */
    }
  }, []);

  useEffect(() => {
    if (typeof Notification !== "undefined") setPerm(Notification.permission);
    poll();
    const t = setInterval(poll, 60_000);
    return () => clearInterval(t);
  }, [poll]);

  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  const readAll = async () => {
    await api("/api/alerts/read-all", { method: "POST" }).catch(() => undefined);
    poll();
  };

  const requestPerm = async () => {
    if (typeof Notification === "undefined") return;
    const p = await Notification.requestPermission();
    setPerm(p);
  };

  const n = alerts.length;
  return (
    <div className="relative" ref={box}>
      <button className="btn btn-ghost relative px-2" aria-label={`Alerts (${n} unread)`} data-testid="alerts-bell" onClick={() => setOpen((o) => !o)}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
          <path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {n > 0 && <span className="absolute -right-1 -top-1 rounded-full bg-sky-500 px-1 text-[9px] font-bold text-white num">{n > 99 ? "99+" : n}</span>}
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-1 w-[min(92vw,380px)] rounded-lg border border-line2 bg-panel shadow-2xl">
          <div className="flex items-center justify-between border-b border-line px-3 py-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-sub">Unread alerts</span>
            <div className="flex gap-1.5">
              {perm !== "granted" && typeof Notification !== "undefined" && (
                <button className="btn btn-ghost px-2 py-0.5 text-[10px]" onClick={requestPerm} disabled={perm === "denied"}>
                  {perm === "denied" ? "Notifications blocked" : "Enable browser notifications"}
                </button>
              )}
              <button className="btn btn-ghost px-2 py-0.5 text-[10px]" onClick={readAll} disabled={!n}>
                Mark all read
              </button>
            </div>
          </div>
          <ul className="max-h-96 overflow-y-auto">
            {n === 0 && <li className="px-3 py-6 text-center text-xs text-sub">No unread alerts.</li>}
            {alerts.map((a) => (
              <li key={a.id} className="border-b border-line px-3 py-2 last:border-0">
                <div className="flex items-center gap-1.5">
                  <Badge tone={a.severity === "WARN" || a.severity === "WARNING" ? "amber" : a.severity === "ERROR" ? "red" : "blue"}>{a.severity}</Badge>
                  <DemoBadge show={a.is_demo} />
                  <span className={cx("truncate text-xs font-semibold")}>{a.title}</span>
                </div>
                <p className="mt-1 text-[11px] text-sub">{a.body}</p>
                <div className="mt-0.5 text-[10px] text-dim">
                  {a.kind} · <Time iso={a.created_at} />
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

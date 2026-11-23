"use client";

import { useEffect } from "react";
import { useApp } from "@/lib/app-context";
import { fmtTime, fmtUtc, isNum, pct, signClass, signedPct } from "@/lib/format";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-lg font-semibold tracking-wide text-ink">{title}</h1>
        {subtitle && <p className="mt-0.5 text-xs text-sub">{subtitle}</p>}
      </div>
      {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
    </div>
  );
}

export function Card({
  title,
  right,
  children,
  className,
  bodyClass,
  testId,
}: {
  title?: React.ReactNode;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClass?: string;
  testId?: string;
}) {
  return (
    <section data-testid={testId} className={cx("min-w-0 rounded-lg border border-line bg-panel", className)}>
      {(title || right) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-sub">{title}</h2>
          {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
        </header>
      )}
      <div className={cx("p-3", bodyClass)}>{children}</div>
    </section>
  );
}

/** Horizontal-scroll container for dense tables inside a card. */
export function TableWrap({ children, maxH }: { children: React.ReactNode; maxH?: string }) {
  return <div className={cx("-mx-3 overflow-x-auto first:-mt-3 last:-mb-3", maxH && "overflow-y-auto")} style={maxH ? { maxHeight: maxH } : undefined}>{children}</div>;
}

const BADGE_TONES: Record<string, string> = {
  green: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  amber: "bg-amber-500/10 text-amber-400 border-amber-500/30",
  gray: "bg-slate-500/10 text-slate-400 border-slate-500/30",
  blue: "bg-sky-500/10 text-sky-300 border-sky-500/30",
  red: "bg-red-500/10 text-red-400 border-red-500/30",
  violet: "bg-violet-500/10 text-violet-300 border-violet-500/30",
};

export function Badge({ tone = "gray", children, title, testId }: { tone?: keyof typeof BADGE_TONES | string; children: React.ReactNode; title?: string; testId?: string }) {
  return (
    <span
      data-testid={testId}
      title={title}
      className={cx("inline-flex items-center rounded border px-1.5 py-[1px] text-[10px] font-semibold uppercase tracking-wider whitespace-nowrap", BADGE_TONES[tone] || BADGE_TONES.gray)}
    >
      {children}
    </span>
  );
}

export function DemoBadge({ show = true }: { show?: boolean | null }) {
  if (!show) return null;
  return (
    <Badge tone="amber" title="Synthetic demo data — not a real match, odds or result" testId="demo-badge">
      DEMO
    </Badge>
  );
}

export function FreshnessBadge({ status, title }: { status: string | null | undefined; title?: string }) {
  const s = status || "UNAVAILABLE";
  const tone = s === "VERIFIED" ? "green" : s === "STALE" ? "amber" : "gray";
  return (
    <Badge tone={tone} title={title || (s === "VERIFIED" ? "Fresh quote within max age" : s === "STALE" ? "Quote older than the allowed age" : "No usable quote")}>
      {s}
    </Badge>
  );
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const s = status || "—";
  const tone =
    s === "QUALIFIES" || s === "CHAMPION" || s === "OK" || s === "LIVE" || s === "POSITIVE"
      ? "blue"
      : s === "WATCH" || s === "DELAYED" || s === "SETTLEMENT_REVIEW" || s === "CANDIDATE" || s === "WARN" || s === "DEGRADED" || s === "INCONCLUSIVE"
        ? "amber"
        : s === "WON"
          ? "green"
          : s === "LOST" || s === "ERROR" || s === "DRIFT" || s === "NEGATIVE" || s === "FAILED"
            ? "red"
            : "gray";
  return <Badge tone={tone}>{s.replace(/_/g, " ")}</Badge>;
}

export function DraftKingsNote() {
  return (
    <Badge tone="gray" title="DraftKings is shown for reference only" testId="dk-reference">
      Reference only — not executable in Florida
    </Badge>
  );
}

export function Time({ iso, dateOnly, timeOnly }: { iso: string | null | undefined; dateOnly?: boolean; timeOnly?: boolean }) {
  const { tz } = useApp();
  if (!iso) return <span className="text-dim">—</span>;
  let txt = fmtTime(iso, tz, !timeOnly);
  if (dateOnly) {
    try {
      txt = new Intl.DateTimeFormat("en-US", { timeZone: tz, month: "short", day: "2-digit", year: "numeric" }).format(new Date(iso));
    } catch {
      /* keep */
    }
  }
  return (
    <time dateTime={iso} title={fmtUtc(iso)} className="num">
      {txt}
    </time>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="py-6 text-center text-xs text-sub">{label}</div>;
}

export function ErrorBox({ error, onRetry }: { error: string | null; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div role="alert" className="my-2 flex flex-wrap items-center justify-between gap-2 rounded-md border border-red-500/30 bg-red-500/5 px-3 py-2 text-xs text-red-300">
      <span>{error}</span>
      {onRetry && (
        <button className="btn btn-ghost" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="py-6 text-center text-xs text-sub">{children}</div>;
}

export function Notice({ tone = "gray", children }: { tone?: "gray" | "amber" | "blue" | "red"; children: React.ReactNode }) {
  const c = {
    gray: "border-line2 bg-panel2 text-sub",
    amber: "border-amber-500/30 bg-amber-500/5 text-amber-300",
    blue: "border-sky-500/30 bg-sky-500/5 text-sky-300",
    red: "border-red-500/30 bg-red-500/5 text-red-300",
  }[tone];
  return <div className={cx("rounded-md border px-3 py-2 text-xs", c)}>{children}</div>;
}

export function Kpi({ label, value, sub, valueClass, testId }: { label: string; value: React.ReactNode; sub?: React.ReactNode; valueClass?: string; testId?: string }) {
  return (
    <div data-testid={testId} className="min-w-0 rounded-lg border border-line bg-panel px-3 py-2">
      <div className="text-[10px] font-semibold uppercase leading-tight tracking-wider text-sub">{label}</div>
      <div className={cx("num mt-0.5 truncate text-base font-semibold", valueClass)}>{value}</div>
      {sub && <div className="num truncate text-[11px] text-dim">{sub}</div>}
    </div>
  );
}

export function EvValue({ ev, digits = 1 }: { ev: number | null | undefined; digits?: number }) {
  return <span className={cx("num font-medium", signClass(ev))}>{signedPct(ev, digits)}</span>;
}

export function Money({ v, signed }: { v: number | null | undefined; signed?: boolean }) {
  const s = !isNum(v)
    ? "—"
    : (v < 0 ? "-" : signed && v > 0 ? "+" : "") + Math.abs(v).toLocaleString("en-US", { style: "currency", currency: "USD" });
  return <span className={cx("num", signed && signClass(v))}>{s}</span>;
}

export function ProbCI({ p, ci }: { p: number | null | undefined; ci?: (number | null)[] | null }) {
  return (
    <span className="num">
      {pct(p)}
      {ci && isNum(ci[0]) && isNum(ci[1]) && (
        <span className="ml-1 text-[11px] text-dim">
          [{pct(ci[0], 0)}–{pct(ci[1], 0)}]
        </span>
      )}
    </span>
  );
}

export function Field({ label, children, hint, className }: { label: string; children: React.ReactNode; hint?: React.ReactNode; className?: string }) {
  return (
    <label className={cx("block min-w-0", className)}>
      <span className="lbl">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-dim">{hint}</span>}
    </label>
  );
}

export function Modal({ open, onClose, title, children, wide, testId }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode; wide?: boolean; testId?: string }) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-3 pt-10" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label={title} data-testid={testId} className={cx("w-full rounded-lg border border-line2 bg-panel shadow-2xl", wide ? "max-w-3xl" : "max-w-xl")}>
        <header className="flex items-center justify-between border-b border-line px-4 py-2.5">
          <h2 className="text-sm font-semibold tracking-wide">{title}</h2>
          <button className="btn btn-ghost px-2" aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </header>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}

export function Drawer({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/50" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside role="dialog" aria-label={title} className="h-full w-full max-w-2xl overflow-y-auto border-l border-line2 bg-bg">
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-panel px-4 py-2.5">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button className="btn btn-ghost px-2" aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </header>
        <div className="space-y-3 p-4">{children}</div>
      </aside>
    </div>
  );
}

export function Tabs<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex overflow-hidden rounded-md border border-line2" role="tablist">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={cx("px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider", value === o.value ? "bg-sky-500/15 text-sky-300" : "text-sub hover:text-ink")}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function KV({ k, v }: { k: React.ReactNode; v: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line/60 py-1 last:border-0">
      <span className="text-sub">{k}</span>
      <span className="num text-right">{v}</span>
    </div>
  );
}

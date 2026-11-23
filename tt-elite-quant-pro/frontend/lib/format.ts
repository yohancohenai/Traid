export function isNum(x: unknown): x is number {
  return typeof x === "number" && Number.isFinite(x);
}

export function pct(x: number | null | undefined, digits = 1): string {
  return isNum(x) ? `${(x * 100).toFixed(digits)}%` : "—";
}

export function signedPct(x: number | null | undefined, digits = 1): string {
  return isNum(x) ? `${x > 0 ? "+" : ""}${(x * 100).toFixed(digits)}%` : "—";
}

export function american(x: number | null | undefined): string {
  if (!isNum(x)) return "—";
  const r = Math.round(x);
  return r > 0 ? `+${r}` : `${r}`;
}

export function dec(x: number | null | undefined, digits = 2): string {
  return isNum(x) ? x.toFixed(digits) : "—";
}

export function num(x: number | null | undefined, digits = 2): string {
  return isNum(x) ? x.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "—";
}

export function usd(x: number | null | undefined, signed = false): string {
  if (!isNum(x)) return "—";
  const s = Math.abs(x).toLocaleString("en-US", { style: "currency", currency: "USD" });
  if (x < 0) return `-${s}`;
  return signed && x > 0 ? `+${s}` : s;
}

export function americanToDecimal(a: number): number | null {
  if (!isNum(a) || (a > -100 && a < 100)) return null;
  return a > 0 ? 1 + a / 100 : 1 + 100 / Math.abs(a);
}

export function decimalToAmerican(d: number): number | null {
  if (!isNum(d) || d <= 1) return null;
  return d >= 2 ? Math.round((d - 1) * 100) : Math.round(-100 / (d - 1));
}

/** Tailwind class for the sign of a P/L or EV value (green/red only used here). */
export function signClass(x: number | null | undefined): string {
  if (!isNum(x) || x === 0) return "text-ink";
  return x > 0 ? "text-pos" : "text-neg";
}

export function fmtTime(iso: string | null | undefined, tz: string, withDate = true): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  const opts: Intl.DateTimeFormatOptions = withDate
    ? { timeZone: tz, month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }
    : { timeZone: tz, hour: "2-digit", minute: "2-digit", hour12: false };
  try {
    return new Intl.DateTimeFormat("en-US", opts).format(d);
  } catch {
    return d.toISOString();
  }
}

export function fmtUtc(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC");
}

export function ago(seconds: number | null | undefined): string {
  if (!isNum(seconds)) return "—";
  const s = Math.max(0, seconds);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${(s / 3600).toFixed(1)}h ago`;
  return `${(s / 86400).toFixed(1)}d ago`;
}

export function agoFromIso(iso: string | null | undefined): string {
  if (!iso) return "—";
  return ago((Date.now() - new Date(iso).getTime()) / 1000);
}

export function marketLabel(m: string): string {
  return m.replace(/_/g, " ");
}

/** Convert a datetime-local input value (browser local time) to ISO UTC. */
export function localInputToIso(v: string): string {
  return new Date(v).toISOString();
}

export function nowLocalInput(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

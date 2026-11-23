"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useApp } from "@/lib/app-context";
import { fmtTime } from "@/lib/format";
import type { ReliabilityBin } from "@/lib/types";

export const SERIES = ["#38bdf8", "#a78bfa", "#2dd4bf", "#f472b6", "#facc15", "#94a3b8"];
const GRID = "#1f2a3c";
const AXIS = { stroke: "#475569", fontSize: 10, tickLine: false } as const;
const TT = {
  contentStyle: { background: "#0f172a", border: "1px solid #2a3850", borderRadius: 6, fontSize: 11 },
  labelStyle: { color: "#94a3b8" },
  itemStyle: { padding: 0 },
};

export interface LineDef {
  key: string;
  name: string;
  color?: string;
  dashed?: boolean;
}

type Row = Record<string, unknown>;

export function TimeLineChart({
  data,
  lines,
  height = 240,
  yFmt = (v: number) => String(v),
  yDomain,
  zeroLine,
  step,
}: {
  data: Row[];
  lines: LineDef[];
  height?: number;
  yFmt?: (v: number) => string;
  yDomain?: [number | string, number | string];
  zeroLine?: boolean;
  step?: boolean;
}) {
  const { tz } = useApp();
  if (!data.length) return <div className="py-8 text-center text-xs text-sub">No data yet.</div>;
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
          <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} {...AXIS} tickFormatter={(v: number) => fmtTime(new Date(v).toISOString(), tz).replace(/,.*/, "")} minTickGap={30} />
          <YAxis {...AXIS} width={56} tickFormatter={yFmt} domain={yDomain || ["auto", "auto"]} />
          <Tooltip {...TT} labelFormatter={(v) => fmtTime(new Date(Number(v)).toISOString(), tz)} formatter={(v) => (typeof v === "number" ? yFmt(v) : String(v))} />
          {lines.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
          {zeroLine && <ReferenceLine y={0} stroke="#475569" />}
          {lines.map((l, i) => (
            <Line
              key={l.key}
              type={step ? "stepAfter" : "monotone"}
              dataKey={l.key}
              name={l.name}
              stroke={l.color || SERIES[i % SERIES.length]}
              strokeDasharray={l.dashed ? "4 3" : undefined}
              dot={false}
              strokeWidth={1.6}
              connectNulls
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function IndexLineChart({ data, xKey, lines, height = 240, yFmt = (v: number) => String(v), zeroLine }: { data: Row[]; xKey: string; lines: LineDef[]; height?: number; yFmt?: (v: number) => string; zeroLine?: boolean }) {
  if (!data.length) return <div className="py-8 text-center text-xs text-sub">No data yet.</div>;
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
          <XAxis dataKey={xKey} type="number" domain={["dataMin", "dataMax"]} {...AXIS} />
          <YAxis {...AXIS} width={56} tickFormatter={yFmt} />
          <Tooltip {...TT} formatter={(v) => (typeof v === "number" ? yFmt(v) : String(v))} />
          {lines.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
          {zeroLine && <ReferenceLine y={0} stroke="#475569" />}
          {lines.map((l, i) => (
            <Line key={l.key} type="linear" dataKey={l.key} name={l.name} stroke={l.color || SERIES[i % SERIES.length]} dot={false} strokeWidth={1.5} connectNulls isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SimpleBarChart({ data, xKey, bars, height = 220, yFmt = (v: number) => String(v) }: { data: Row[]; xKey: string; bars: LineDef[]; height?: number; yFmt?: (v: number) => string }) {
  if (!data.length) return <div className="py-8 text-center text-xs text-sub">No data.</div>;
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={xKey} {...AXIS} />
          <YAxis {...AXIS} width={48} tickFormatter={yFmt} />
          <Tooltip {...TT} cursor={{ fill: "rgba(56,189,248,.06)" }} formatter={(v) => (typeof v === "number" ? yFmt(v) : String(v))} />
          {bars.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
          {bars.map((b, i) => (
            <Bar key={b.key} dataKey={b.key} name={b.name} fill={b.color || SERIES[i % SERIES.length]} radius={[2, 2, 0, 0]} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

const ORDER = ["3-0", "3-1", "3-2", "2-3", "1-3", "0-3"];

export function ScorelineChart({ scorelines, height = 200 }: { scorelines: Record<string, number> | null | undefined; height?: number }) {
  if (!scorelines) return <div className="py-6 text-center text-xs text-sub">No scoreline distribution.</div>;
  const data = ORDER.filter((k) => k in scorelines).map((k) => ({ score: k, p: scorelines[k] }));
  return <SimpleBarChart data={data} xKey="score" bars={[{ key: "p", name: "Probability" }]} height={height} yFmt={(v) => `${(v * 100).toFixed(0)}%`} />;
}

export function ReliabilityChart({ bins, height = 260 }: { bins: ReliabilityBin[]; height?: number }) {
  const pts = bins.filter((b) => b.n > 0 && b.mean_pred != null && b.obs_rate != null).map((b) => ({ x: b.mean_pred as number, y: b.obs_rate as number, n: b.n }));
  if (!pts.length) return <div className="py-8 text-center text-xs text-sub">No reliability data.</div>;
  const diag = [
    { x: 0, d: 0 },
    { x: 1, d: 1 },
  ];
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart margin={{ top: 6, right: 12, bottom: 12, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
          <XAxis dataKey="x" type="number" domain={[0, 1]} {...AXIS} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} label={{ value: "Predicted", position: "insideBottom", offset: -6, fill: "#64748b", fontSize: 10 }} />
          <YAxis type="number" domain={[0, 1]} {...AXIS} width={44} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} />
          <Tooltip {...TT} formatter={(v, name) => (typeof v === "number" && name !== "n" ? `${(v * 100).toFixed(1)}%` : String(v))} />
          <Line data={diag} dataKey="d" name="Perfect calibration" stroke="#475569" strokeDasharray="4 3" dot={false} isAnimationActive={false} />
          <Scatter data={pts} dataKey="y" name="Observed" fill="#38bdf8" line={{ stroke: "#38bdf8" }} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Convert an array of {at: iso} rows into rows with numeric t for TimeLineChart. */
export function withT<T extends { at: string }>(rows: T[]): (T & { t: number })[] {
  return rows.map((r) => ({ ...r, t: new Date(r.at).getTime() }));
}

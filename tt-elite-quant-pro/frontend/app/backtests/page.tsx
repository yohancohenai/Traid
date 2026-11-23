"use client";

import { useEffect, useMemo, useState } from "react";
import { IndexLineChart, ReliabilityChart } from "@/components/charts";
import { Card, Empty, ErrorBox, Field, Loading, Notice, PageHeader, StatusBadge, TableWrap, Time, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { dec, isNum, num, pct, signClass, signedPct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { ReliabilityBin } from "@/lib/types";

interface BtListRow {
  id: number;
  name: string;
  created_at: string;
  outcome: string;
  config: Record<string, unknown>;
  model: string | null;
  bets: number | null;
  roi: number | null;
}
interface Strat {
  roi: number | null;
  bets: number;
  note?: string;
  curve?: { i: number; cum: number }[];
  avg_ev?: number;
  avg_clv?: number;
  avg_odds?: number;
  roi_ci95?: [number, number];
  win_rate?: number;
  profit_units?: number;
  staked_units?: number;
  max_drawdown_units?: number;
  clv_positive_rate?: number;
  p_roi_le_0_bootstrap?: number;
  bets_per_day?: number;
}
interface BtDetail {
  id: number;
  name: string;
  created_at: string;
  outcome: string;
  is_demo: boolean;
  period_start: string | null;
  period_end: string | null;
  config: { period?: string; slippage?: number; decision_minutes?: number; delay_minutes?: number; filters?: Record<string, unknown> };
  metrics: {
    status?: string;
    period?: string;
    strategies?: Record<string, Strat>;
    probability?: {
      n: number;
      model?: { brier: number; log_loss: number };
      reliability?: ReliabilityBin[];
      model_on_priced?: { n: number; brier: number; log_loss: number };
      hardrock_novig_on_priced?: { brier: number; log_loss: number };
    };
    demo_warning?: string | null;
    model_version?: string;
    multiple_testing?: { note: string; runs_so_far: number };
    slippage_sensitivity?: Record<string, number | null>;
  };
}

const STRATS = ["model", "elo_only", "glicko_only", "market_consensus", "novig"];

export default function BacktestsPage() {
  const { demo } = useApp();
  const list = useApi<BtListRow[]>("/api/backtests", { demo });
  const [sel, setSel] = useState<number | null>(null);
  useEffect(() => {
    if (list.data && list.data.length && (sel == null || !list.data.some((r) => r.id === sel))) setSel(list.data[0].id);
    if (list.data && !list.data.length) setSel(null);
  }, [list.data, sel]);

  return (
    <div className="space-y-3">
      <PageHeader title="BACKTESTING" subtitle="Walk-forward simulation against archived Hard Rock prices. Past simulated performance does not predict future results." />
      <div className="grid gap-3 xl:grid-cols-3">
        <Card title="Runs" className="xl:col-span-2">
          <ErrorBox error={list.error} onRetry={list.reload} />
          {list.loading && !list.data && <Loading />}
          {list.data && list.data.length === 0 && <Empty>No backtests yet. Run one with the form.</Empty>}
          {list.data && list.data.length > 0 && (
            <TableWrap maxH="300px">
              <table className="tbl">
                <thead>
                  <tr>
                    <th className="r">#</th>
                    <th>Created</th>
                    <th>Name</th>
                    <th>Period</th>
                    <th>Model</th>
                    <th className="r">Bets</th>
                    <th className="r">ROI</th>
                    <th>Outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.map((r) => (
                    <tr key={r.id} className={cx("cursor-pointer", sel === r.id && "bg-sky-500/10")} onClick={() => setSel(r.id)}>
                      <td className="r text-dim">{r.id}</td>
                      <td>
                        <Time iso={r.created_at} />
                      </td>
                      <td>{r.name}</td>
                      <td>{String(r.config?.period ?? "—")}</td>
                      <td className="text-sub">{r.model || "—"}</td>
                      <td className="r">{r.bets ?? "—"}</td>
                      <td className={cx("r", signClass(r.roi))}>{signedPct(r.roi)}</td>
                      <td>
                        <StatusBadge status={r.outcome} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          )}
        </Card>
        <RunForm demo={demo} onDone={(id) => { list.reload(); if (id) setSel(id); }} />
      </div>
      {sel != null && <BacktestDetail id={sel} />}
    </div>
  );
}

function RunForm({ demo, onDone }: { demo: boolean; onDone: (id?: number) => void }) {
  const [name, setName] = useState("manual run");
  const [period, setPeriod] = useState("test");
  const [slip, setSlip] = useState("0.01");
  const [decMin, setDecMin] = useState("30");
  const [delay, setDelay] = useState("2");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "red" | "blue" | "amber"; text: React.ReactNode } | null>(null);
  const [fbusy, setFbusy] = useState(false);

  const run = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const r = await api<{ status: string; id?: number; outcome?: string }>("/api/backtests", {
        body: { name, demo, period, slippage: Number(slip), decision_minutes: Number(decMin), delay_minutes: Number(delay) },
      });
      setMsg(r.status === "OK" ? { tone: "blue", text: `Run #${r.id} finished: ${r.outcome}.` } : { tone: "amber", text: `Backtest status: ${r.status}` });
      onDone(r.id);
    } catch (e2) {
      setMsg({ tone: "red", text: (e2 as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const selectFilters = async () => {
    setFbusy(true);
    setMsg(null);
    try {
      const r = await api<{ status: string; chosen?: { min_ev: number; min_edge: number }; grid?: { min_ev: number; min_edge: number; bets: number; roi: number | null; roi_ci_low: number | null }[] }>("/api/backtests/select-filters", {
        method: "POST",
        query: { demo },
      });
      setMsg({
        tone: r.status === "OK" ? "blue" : "amber",
        text: (
          <div>
            <div>
              {r.status === "OK" ? `Filters selected on calibration period: min Estimated EV ${pct(r.chosen?.min_ev)}, min edge ${pct(r.chosen?.min_edge)}.` : `No filter candidate selected (${r.status}).`}
            </div>
            {r.grid && (
              <table className="tbl mt-2">
                <thead>
                  <tr>
                    <th className="r">Min Est. EV</th>
                    <th className="r">Min edge</th>
                    <th className="r">Bets</th>
                    <th className="r">ROI</th>
                    <th className="r">ROI CI low</th>
                  </tr>
                </thead>
                <tbody>
                  {r.grid.map((gr, i) => (
                    <tr key={i}>
                      <td className="r">{pct(gr.min_ev)}</td>
                      <td className="r">{pct(gr.min_edge)}</td>
                      <td className="r">{gr.bets}</td>
                      <td className="r">{signedPct(gr.roi)}</td>
                      <td className="r">{signedPct(gr.roi_ci_low)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        ),
      });
    } catch (e2) {
      setMsg({ tone: "red", text: (e2 as Error).message });
    } finally {
      setFbusy(false);
    }
  };

  return (
    <Card title="Run backtest">
      <form onSubmit={run} className="space-y-2">
        <Field label="Name">
          <input className="inp w-full" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Period">
            <select className="inp w-full" value={period} onChange={(e) => setPeriod(e.target.value)}>
              <option value="tune">tune</option>
              <option value="calib">calib</option>
              <option value="test">test</option>
            </select>
          </Field>
          <Field label="Slippage (0–0.2)">
            <input className="inp w-full num" value={slip} onChange={(e) => setSlip(e.target.value)} />
          </Field>
          <Field label="Decision minutes before">
            <input className="inp w-full num" value={decMin} onChange={(e) => setDecMin(e.target.value)} />
          </Field>
          <Field label="Execution delay minutes">
            <input className="inp w-full num" value={delay} onChange={(e) => setDelay(e.target.value)} />
          </Field>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? "Running…" : "Run backtest"}
          </button>
          <button type="button" className="btn" onClick={selectFilters} disabled={fbusy}>
            {fbusy ? "Selecting…" : "Select filters on calibration period"}
          </button>
        </div>
        <p className="text-[11px] text-dim">Filters are chosen on the calibration period only, never on the test period.</p>
        {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
      </form>
    </Card>
  );
}

function BacktestDetail({ id }: { id: number }) {
  const { data, error, loading, reload } = useApi<BtDetail>(`/api/backtests/${id}`);
  const curves = useMemo(() => {
    const s = data?.metrics.strategies || {};
    const map = new Map<number, Record<string, number>>();
    for (const k of STRATS) for (const p of s[k]?.curve || []) {
      const row = map.get(p.i) || { i: p.i };
      row[k] = p.cum;
      map.set(p.i, row);
    }
    return [...map.values()].sort((a, b) => a.i - b.i);
  }, [data]);

  if (loading && !data) return <Loading />;
  if (!data) return <ErrorBox error={error} onRetry={reload} />;
  const m = data.metrics;
  const strategies = m.strategies || {};
  const prob = m.probability;

  return (
    <div className="space-y-3">
      <Card title={`Run #${data.id} — ${data.name}`} right={<StatusBadge status={data.outcome} />}>
        {m.demo_warning && <div className="mb-2"><Notice tone="amber">{m.demo_warning}</Notice></div>}
        <div className="grid gap-2 text-xs sm:grid-cols-4">
          <div>
            <div className="lbl">Period</div>
            {data.config.period} · <Time iso={data.period_start} dateOnly /> → <Time iso={data.period_end} dateOnly />
          </div>
          <div>
            <div className="lbl">Model</div>
            {m.model_version || "—"}
          </div>
          <div>
            <div className="lbl">Slippage / decision / delay</div>
            <span className="num">
              {data.config.slippage} · {data.config.decision_minutes}m · {data.config.delay_minutes}m
            </span>
          </div>
          <div>
            <div className="lbl">Created</div>
            <Time iso={data.created_at} />
          </div>
        </div>
        {m.status && m.status !== "OK" && <div className="mt-2"><Notice tone="amber">Status: {m.status}</Notice></div>}
      </Card>

      {prob && (
        <div className="grid gap-3 lg:grid-cols-2">
          <Card title="Probability metrics — model vs Hard Rock no-vig">
            <TableWrap>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Forecast</th>
                    <th className="r">n</th>
                    <th className="r">Log loss</th>
                    <th className="r">Brier</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Model (all)</td>
                    <td className="r">{prob.n}</td>
                    <td className="r">{dec(prob.model?.log_loss, 4)}</td>
                    <td className="r">{dec(prob.model?.brier, 4)}</td>
                  </tr>
                  <tr>
                    <td>Model (priced matches)</td>
                    <td className="r">{prob.model_on_priced?.n ?? "—"}</td>
                    <td className="r">{dec(prob.model_on_priced?.log_loss, 4)}</td>
                    <td className="r">{dec(prob.model_on_priced?.brier, 4)}</td>
                  </tr>
                  <tr>
                    <td>Hard Rock no-vig (priced)</td>
                    <td className="r">{prob.model_on_priced?.n ?? "—"}</td>
                    <td className="r">{dec(prob.hardrock_novig_on_priced?.log_loss, 4)}</td>
                    <td className="r">{dec(prob.hardrock_novig_on_priced?.brier, 4)}</td>
                  </tr>
                </tbody>
              </table>
            </TableWrap>
          </Card>
          <Card title="Reliability (test period)">
            <ReliabilityChart bins={prob.reliability || []} height={220} />
          </Card>
        </div>
      )}

      <Card title="Strategy comparison">
        <TableWrap>
          <table className="tbl">
            <thead>
              <tr>
                <th>Strategy</th>
                <th className="r">Bets</th>
                <th className="r">Win rate</th>
                <th className="r">Avg odds</th>
                <th className="r">Avg Estimated EV</th>
                <th className="r">Profit (u)</th>
                <th className="r">ROI</th>
                <th className="r">ROI CI95</th>
                <th className="r">P(ROI ≤ 0)</th>
                <th className="r">Avg CLV</th>
                <th className="r">CLV+ rate</th>
                <th className="r">Max drawdown (u)</th>
              </tr>
            </thead>
            <tbody>
              {STRATS.filter((k) => strategies[k]).map((k) => {
                const s = strategies[k];
                return (
                  <tr key={k}>
                    <td className="font-medium">{k}</td>
                    <td className="r">{s.bets}</td>
                    <td className="r">{pct(s.win_rate)}</td>
                    <td className="r">{dec(s.avg_odds)}</td>
                    <td className={cx("r", signClass(s.avg_ev))}>{signedPct(s.avg_ev)}</td>
                    <td className={cx("r", signClass(s.profit_units))}>{num(s.profit_units)}</td>
                    <td className={cx("r", signClass(s.roi))}>{signedPct(s.roi)}</td>
                    <td className="r">{s.roi_ci95 ? `${signedPct(s.roi_ci95[0])} … ${signedPct(s.roi_ci95[1])}` : "—"}</td>
                    <td className="r">{pct(s.p_roi_le_0_bootstrap)}</td>
                    <td className="r">{signedPct(s.avg_clv)}</td>
                    <td className="r">{pct(s.clv_positive_rate)}</td>
                    <td className="r">{num(s.max_drawdown_units)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </TableWrap>
        {STRATS.filter((k) => strategies[k]?.note).map((k) => (
          <p key={k} className="mt-1 text-[11px] text-dim">
            {k}: {strategies[k].note}
          </p>
        ))}
      </Card>

      <div className="grid gap-3 lg:grid-cols-3">
        <Card title="Equity curve (cumulative units)" className="lg:col-span-2">
          <IndexLineChart data={curves} xKey="i" lines={STRATS.filter((k) => strategies[k]?.curve?.length).map((k) => ({ key: k, name: k }))} height={280} yFmt={(v) => v.toFixed(1)} zeroLine />
        </Card>
        <div className="space-y-3">
          <Card title="Slippage sensitivity (model ROI)">
            {m.slippage_sensitivity ? (
              <table className="tbl">
                <tbody>
                  {Object.entries(m.slippage_sensitivity).map(([k, v]) => (
                    <tr key={k}>
                      <td>{k.replace("slippage_", "slippage ")}</td>
                      <td className={cx("r", signClass(v))}>{isNum(v) ? signedPct(v) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty>Not available.</Empty>
            )}
          </Card>
          {m.multiple_testing && (
            <Notice tone="amber">
              <b>Multiple testing:</b> {m.multiple_testing.note} Runs so far: {m.multiple_testing.runs_so_far}.
            </Notice>
          )}
        </div>
      </div>
    </div>
  );
}

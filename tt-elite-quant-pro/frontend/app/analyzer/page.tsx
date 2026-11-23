"use client";

import { useState } from "react";
import { ScorelineChart } from "@/components/charts";
import { PlayerPicker } from "@/components/player-picker";
import { Card, ErrorBox, EvValue, Field, KV, Loading, Notice, PageHeader, TableWrap } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { american, dec, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { PlayerRef } from "@/lib/types";

interface Sens {
  prob_shift: number;
  prob: number;
  ev: number;
}
interface AnalyzeOut {
  model: string;
  p1_win: number;
  p1_ci: [number, number];
  components: Record<string, number>;
  rating_probs: Record<string, number>;
  data_quality: string;
  sample: [number, number];
  scorelines: Record<string, number>;
  p_game: number;
  p_point: number;
  fair: { p1: { decimal: number; american: number }; p2: { decimal: number; american: number } };
  market?: {
    overround: number;
    novig_mult: [number, number];
    novig_power: [number, number];
    novig_shin: [number, number];
    ev_p1: number;
    ev_p2: number;
    break_even: [number, number];
    sensitivity_p1: Sens[];
    sensitivity_p2: Sens[];
  };
}

export default function AnalyzerPage() {
  const { demo } = useApp();
  const players = useApi<{ id: number; name: string }[]>("/api/players", { demo, limit: 2000 });
  const [p1, setP1] = useState<PlayerRef | null>(null);
  const [p2, setP2] = useState<PlayerRef | null>(null);
  const [o1, setO1] = useState("");
  const [o2, setO2] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [out, setOut] = useState<AnalyzeOut | null>(null);
  const [names, setNames] = useState<[string, string]>(["P1", "P2"]);

  const plist: PlayerRef[] = (players.data || []).map((p) => ({ id: p.id, name: p.name })).sort((a, b) => a.name.localeCompare(b.name));

  const parseAm = (s: string): number | null | "bad" => {
    if (!s.trim()) return null;
    const n = Number(s);
    if (!Number.isInteger(n) || (n > -100 && n < 100)) return "bad";
    return n;
  };

  const run = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    if (!p1 || !p2) return setErr("Choose two players.");
    if (p1.id === p2.id) return setErr("Choose two different players.");
    const a1 = parseAm(o1);
    const a2 = parseAm(o2);
    if (a1 === "bad" || a2 === "bad") return setErr("American odds must be ≤ -100 or ≥ +100.");
    setBusy(true);
    try {
      const r = await api<AnalyzeOut>("/api/analyzer", { body: { player1_id: p1.id, player2_id: p2.id, demo, p1_american: a1, p2_american: a2 } });
      setOut(r);
      setNames([p1.name, p2.name]);
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <PageHeader title="MATCH ANALYZER" subtitle="Hypothetical head-to-head using current ratings and form. Add Hard Rock prices to see overround, no-vig and Estimated EV." />
      <Card title="Inputs">
        <ErrorBox error={players.error} onRetry={players.reload} />
        <form onSubmit={run} className="grid gap-3 md:grid-cols-5">
          <div className="md:col-span-2">
            <PlayerPicker label="Player 1" players={plist} value={p1} onChange={setP1} testId="analyzer-p1" />
          </div>
          <div className="md:col-span-2">
            <PlayerPicker label="Player 2" players={plist} value={p2} onChange={setP2} testId="analyzer-p2" />
          </div>
          <div className="hidden md:block" />
          <Field label="P1 American odds (optional)" className="md:col-span-2">
            <input className="inp w-full num" value={o1} onChange={(e) => setO1(e.target.value)} placeholder="-150" />
          </Field>
          <Field label="P2 American odds (optional)" className="md:col-span-2">
            <input className="inp w-full num" value={o2} onChange={(e) => setO2(e.target.value)} placeholder="+125" />
          </Field>
          <div className="flex items-end">
            <button className="btn btn-primary w-full" type="submit" disabled={busy || !p1 || !p2}>
              {busy ? "Analyzing…" : "Analyze"}
            </button>
          </div>
        </form>
        {err && <div className="mt-2"><Notice tone="red">{err}</Notice></div>}
      </Card>

      {busy && !out && <Loading label="Computing features (first run may take a few seconds)…" />}
      {out && (
        <>
          <div className="grid gap-3 lg:grid-cols-3">
            <Card title="Probability" right={<span className="text-[10px] text-dim">{out.model}</span>}>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="rounded bg-panel2 p-2">
                  <div className="truncate text-sub">{names[0]}</div>
                  <div className="num text-xl font-semibold">{pct(out.p1_win)}</div>
                  <div className="num text-[11px] text-dim">
                    CI {pct(out.p1_ci[0])} – {pct(out.p1_ci[1])}
                  </div>
                </div>
                <div className="rounded bg-panel2 p-2">
                  <div className="truncate text-sub">{names[1]}</div>
                  <div className="num text-xl font-semibold">{pct(1 - out.p1_win)}</div>
                  <div className="num text-[11px] text-dim">
                    CI {pct(1 - out.p1_ci[1])} – {pct(1 - out.p1_ci[0])}
                  </div>
                </div>
              </div>
              <div className="mt-2 text-xs">
                <KV k={`Fair odds ${names[0]}`} v={`${american(out.fair.p1.american)} · ${dec(out.fair.p1.decimal, 3)}`} />
                <KV k={`Fair odds ${names[1]}`} v={`${american(out.fair.p2.american)} · ${dec(out.fair.p2.decimal, 3)}`} />
                <KV k="Game / point win prob (P1)" v={`${pct(out.p_game)} / ${pct(out.p_point)}`} />
                <KV k="Data quality" v={out.data_quality} />
                <KV k="Sample (matches)" v={`${out.sample[0]} / ${out.sample[1]}`} />
              </div>
            </Card>
            <Card title="Component & rating-engine probabilities (P1)">
              <TableWrap>
                <table className="tbl">
                  <tbody>
                    {Object.entries(out.components).map(([k, v]) => (
                      <tr key={k}>
                        <td>{k}</td>
                        <td className="text-[10px] text-dim">component</td>
                        <td className="r">{pct(v)}</td>
                      </tr>
                    ))}
                    {Object.entries(out.rating_probs).map(([k, v]) => (
                      <tr key={k}>
                        <td>{k}</td>
                        <td className="text-[10px] text-dim">rating engine</td>
                        <td className="r">{pct(v)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            </Card>
            <Card title="Scoreline distribution (P1 perspective)">
              <ScorelineChart scorelines={out.scorelines} />
            </Card>
          </div>

          {out.market ? (
            <div className="grid gap-3 lg:grid-cols-3">
              <Card title="Market">
                <div className="text-xs">
                  <KV k="Overround" v={pct(out.market.overround, 2)} />
                  <KV k={`No-vig mult. ${names[0]} / ${names[1]}`} v={`${pct(out.market.novig_mult[0])} / ${pct(out.market.novig_mult[1])}`} />
                  <KV k="No-vig power" v={`${pct(out.market.novig_power[0])} / ${pct(out.market.novig_power[1])}`} />
                  <KV k="No-vig Shin" v={`${pct(out.market.novig_shin[0])} / ${pct(out.market.novig_shin[1])}`} />
                  <KV k={`Break-even ${names[0]} / ${names[1]}`} v={`${pct(out.market.break_even[0])} / ${pct(out.market.break_even[1])}`} />
                  <KV k={`Estimated EV ${names[0]}`} v={<EvValue ev={out.market.ev_p1} />} />
                  <KV k={`Estimated EV ${names[1]}`} v={<EvValue ev={out.market.ev_p2} />} />
                </div>
                <p className="mt-2 text-[11px] text-dim">Estimated EV is conditional on the model probability being accurate.</p>
              </Card>
              <SensTable title={`Estimated EV sensitivity — ${names[0]}`} rows={out.market.sensitivity_p1} />
              <SensTable title={`Estimated EV sensitivity — ${names[1]}`} rows={out.market.sensitivity_p2} />
            </div>
          ) : (
            <Notice tone="gray">Enter American odds for both players to see overround, no-vig probabilities and Estimated EV.</Notice>
          )}
        </>
      )}
    </div>
  );
}

function SensTable({ title, rows }: { title: string; rows: Sens[] }) {
  return (
    <Card title={title}>
      <TableWrap>
        <table className="tbl">
          <thead>
            <tr>
              <th className="r">Prob shift</th>
              <th className="r">Win prob</th>
              <th className="r">Estimated EV</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.prob_shift}>
                <td className="r">{r.prob_shift > 0 ? "+" : ""}{(r.prob_shift * 100).toFixed(1)} pp</td>
                <td className="r">{pct(r.prob)}</td>
                <td className="r">
                  <EvValue ev={r.ev} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </Card>
  );
}

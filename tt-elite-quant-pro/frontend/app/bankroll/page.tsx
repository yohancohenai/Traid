"use client";

import { useState } from "react";
import { TimeLineChart, withT } from "@/components/charts";
import { SettingsGroupForm } from "@/components/settings-form";
import { Card, DemoBadge, Empty, ErrorBox, EvValue, Field, Kpi, Loading, Money, Notice, PageHeader, StatusBadge, TableWrap, Tabs, Time } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { dec, pct, signClass, signedPct, usd } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { GroupRow, RiskSettings, Summary } from "@/lib/types";

interface BankrollResp {
  summary: Summary;
  risk: RiskSettings;
  recommendations_ledger: { ledger: string; count: number; graded: number; units: number; roi: number | null; wins: number; losses: number };
}

type G = "by_day" | "by_week" | "by_month" | "by_player" | "by_market" | "by_odds" | "by_model_version";

export default function BankrollPage() {
  const { demo } = useApp();
  const { data, error, loading, reload } = useApi<BankrollResp>("/api/bankroll", { demo });
  const [g, setG] = useState<G>("by_day");
  const [paperOpen, setPaperOpen] = useState(false);

  return (
    <div className="space-y-3">
      <PageHeader title="BANKROLL" subtitle={`Ledger A — your actual recorded bets${demo ? " (DEMO ledger)" : ""}.`} right={<button className="btn btn-ghost" onClick={reload}>Refresh</button>} />
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data && <Loading />}
      {data && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8" data-testid="kpis">
            <Kpi label="Current bankroll" value={usd(data.summary.bankroll)} />
            <Kpi label="Net P/L" value={usd(data.summary.net_pl, true)} valueClass={signClass(data.summary.net_pl)} />
            <Kpi label="ROI" value={signedPct(data.summary.roi)} valueClass={signClass(data.summary.roi)} />
            <Kpi label="Total bets" value={data.summary.total_bets} />
            <Kpi label="Pending" value={data.summary.pending} sub={`exposure ${usd(data.summary.pending_exposure)}`} />
            <Kpi label="Wins" value={data.summary.wins} />
            <Kpi label="Losses" value={data.summary.losses} />
            <Kpi label="Pushes / voids" value={`${data.summary.pushes} / ${data.summary.voids}`} sub={`${data.summary.in_review} in review`} />
            <Kpi label="Win %" value={pct(data.summary.win_pct)} />
            <Kpi label="Wagered" value={usd(data.summary.total_wagered)} />
            <Kpi label="Returned" value={usd(data.summary.total_returned)} />
            <Kpi label="Avg odds (decimal)" value={dec(data.summary.avg_decimal)} />
            <Kpi label="Avg Estimated EV at placement" value={<EvValue ev={data.summary.avg_ev_at_placement} />} />
            <Kpi label="Avg CLV" value={signedPct(data.summary.avg_clv)} sub={`n=${data.summary.clv_n}`} />
            <Kpi label="Max drawdown" value={usd(data.summary.max_drawdown)} />
            <Kpi label="Ledger" value={<span className="text-xs">{data.summary.ledger}</span>} />
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <Card title="Bankroll history">
              <TimeLineChart data={withT(data.summary.bankroll_history)} lines={[{ key: "balance", name: "Balance" }]} height={220} yFmt={(v) => usd(v)} step />
            </Card>
            <Card title="Cumulative realized P/L">
              <TimeLineChart data={withT(data.summary.pl_curve)} lines={[{ key: "cum_pl", name: "Cumulative P/L" }]} height={220} yFmt={(v) => usd(v)} zeroLine />
            </Card>
          </div>

          <Card
            title="Breakdown (settled bets)"
            right={
              <Tabs<G>
                value={g}
                onChange={setG}
                options={[
                  { value: "by_day", label: "Day" },
                  { value: "by_week", label: "Week" },
                  { value: "by_month", label: "Month" },
                  { value: "by_player", label: "Player" },
                  { value: "by_market", label: "Market" },
                  { value: "by_odds", label: "Odds range" },
                  { value: "by_model_version", label: "Model version" },
                ]}
              />
            }
          >
            <GroupTable rows={data.summary[g]} />
          </Card>

          <div className="grid gap-3 lg:grid-cols-2">
            <Card title="Ledger B — recommendations not placed (hypothetical, 1 unit)">
              <Notice tone="gray">Qualifying recommendations you did not place, graded as if 1 unit was staked. Hypothetical — not money you won or lost.</Notice>
              <div className="mt-2 grid grid-cols-3 gap-2">
                <Kpi label="Recommendations" value={data.recommendations_ledger.count} sub={`${data.recommendations_ledger.graded} graded`} />
                <Kpi label="Units" value={`${data.recommendations_ledger.units > 0 ? "+" : ""}${data.recommendations_ledger.units.toFixed(2)}u`} valueClass={signClass(data.recommendations_ledger.units)} />
                <Kpi label="ROI" value={signedPct(data.recommendations_ledger.roi)} valueClass={signClass(data.recommendations_ledger.roi)} sub={`${data.recommendations_ledger.wins}W-${data.recommendations_ledger.losses}L`} />
              </div>
            </Card>
            <Card title="Ledger C — paper trading (hypothetical)" right={<button className="btn btn-ghost" onClick={() => setPaperOpen((o) => !o)}>{paperOpen ? "Hide" : "Open paper ledger"}</button>}>
              <Notice tone="gray">Backtest paper trades (1 unit each). Never real money.</Notice>
              {paperOpen && <PaperLedger demo={demo} />}
            </Card>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <Card title="Deposit / withdrawal">
              <TxForm demo={demo} onDone={reload} />
            </Card>
            <Card title="Risk limits">
              <SettingsGroupForm group="risk" value={data.risk as unknown as Record<string, number>} onSaved={reload} />
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function GroupTable({ rows }: { rows: GroupRow[] }) {
  if (!rows.length) return <Empty>No settled bets yet.</Empty>;
  return (
    <TableWrap maxH="360px">
      <table className="tbl">
        <thead>
          <tr>
            <th>Group</th>
            <th className="r">Bets</th>
            <th className="r">Won</th>
            <th className="r">Lost</th>
            <th className="r">Staked</th>
            <th className="r">Net</th>
            <th className="r">ROI</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={String(r.key)}>
              <td>{String(r.key)}</td>
              <td className="r">{r.bets}</td>
              <td className="r">{r.won}</td>
              <td className="r">{r.lost}</td>
              <td className="r">
                <Money v={r.staked} />
              </td>
              <td className="r">
                <Money v={r.net} signed />
              </td>
              <td className={`r ${signClass(r.roi)}`}>{signedPct(r.roi)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}

function PaperLedger({ demo }: { demo: boolean }) {
  const { data, error, loading, reload } = useApi<{ ledger: string; items: { id: number; match_id: number; backtest_run_id: number | null; selection: string; decimal_odds: number; model_prob: number; ev: number; result: string | null; profit_units: number | null; closing_decimal: number | null; decided_at: string; is_demo: boolean }[] }>(
    "/api/ledgers/paper",
    { demo },
  );
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;
  const units = data.items.reduce((s, x) => s + (x.profit_units || 0), 0);
  return (
    <div className="mt-2 space-y-2">
      <div className="text-xs text-sub">
        {data.ledger} · {data.items.length} trades (latest 500) · <span className={signClass(units)}>{units >= 0 ? "+" : ""}{units.toFixed(2)}u</span>
      </div>
      <TableWrap maxH="300px">
        <table className="tbl">
          <thead>
            <tr>
              <th>Decided</th>
              <th className="r">Match</th>
              <th>Sel.</th>
              <th className="r">Odds</th>
              <th className="r">Model p</th>
              <th className="r">Estimated EV</th>
              <th>Result</th>
              <th className="r">Units</th>
            </tr>
          </thead>
          <tbody>
            {data.items.slice(0, 200).map((t) => (
              <tr key={t.id}>
                <td>
                  <Time iso={t.decided_at} /> <DemoBadge show={t.is_demo} />
                </td>
                <td className="r">{t.match_id}</td>
                <td>{t.selection}</td>
                <td className="r">{dec(t.decimal_odds)}</td>
                <td className="r">{pct(t.model_prob)}</td>
                <td className="r">
                  <EvValue ev={t.ev} />
                </td>
                <td>{t.result ? <StatusBadge status={t.result} /> : "—"}</td>
                <td className={`r ${signClass(t.profit_units)}`}>{t.profit_units != null ? t.profit_units.toFixed(2) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </div>
  );
}

function TxForm({ demo, onDone }: { demo: boolean; onDone: () => void }) {
  const [kind, setKind] = useState("DEPOSIT");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "red" | "blue"; text: string } | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const a = Number(amount);
    if (!(a > 0)) return setMsg({ tone: "red", text: "Amount must be positive." });
    setBusy(true);
    setMsg(null);
    try {
      await api("/api/bankroll/transactions", { body: { kind, amount: a, note: note || null, demo } });
      setMsg({ tone: "blue", text: `${kind} of ${usd(a)} recorded${demo ? " in the DEMO ledger" : ""}.` });
      setAmount("");
      setNote("");
      onDone();
    } catch (e2) {
      setMsg({ tone: "red", text: (e2 as Error).message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} className="space-y-2">
      <div className="grid gap-2 sm:grid-cols-3">
        <Field label="Type">
          <select className="inp w-full" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option>DEPOSIT</option>
            <option>WITHDRAWAL</option>
            <option>ADJUSTMENT</option>
          </select>
        </Field>
        <Field label="Amount USD">
          <input className="inp w-full num" value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" />
        </Field>
        <Field label="Note">
          <input className="inp w-full" value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </div>
      <p className="text-[11px] text-dim">Recorded in the {demo ? "DEMO" : "LIVE"} ledger (follows the header data mode).</p>
      <button className="btn btn-primary" type="submit" disabled={busy}>
        {busy ? "Saving…" : "Record transaction"}
      </button>
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
    </form>
  );
}

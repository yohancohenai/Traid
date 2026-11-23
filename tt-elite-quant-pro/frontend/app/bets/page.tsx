"use client";

import { useRef, useState } from "react";
import { BetModal, MARKETS } from "@/components/bet-modal";
import { Card, DemoBadge, Drawer, Empty, ErrorBox, EvValue, Field, KV, Loading, Money, Notice, PageHeader, StatusBadge, TableWrap, Tabs, Time } from "@/components/ui";
import { api, downloadFile } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { american, dec, localInputToIso, marketLabel, pct, signedPct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { BetRow, MatchBrief } from "@/lib/types";

type SF = "ALL" | "OPEN" | "SETTLEMENT_REVIEW" | "SETTLED";
const SF_Q: Record<SF, string | undefined> = {
  ALL: undefined,
  OPEN: "PLACED,PENDING_RESULT",
  SETTLEMENT_REVIEW: "SETTLEMENT_REVIEW",
  SETTLED: "WON,LOST,PUSH,VOID",
};

export default function BetsPage() {
  const { demo } = useApp();
  const [sf, setSf] = useState<SF>("ALL");
  const [selId, setSelId] = useState<number | null>(null);
  const [manual, setManual] = useState(false);
  const recorded = useRef(false);
  const [exportErr, setExportErr] = useState<string | null>(null);
  const { data, error, loading, reload } = useApi<BetRow[]>("/api/bets", { demo, status: SF_Q[sf] });

  const doExport = async () => {
    setExportErr(null);
    try {
      await downloadFile("/api/bankroll/export.csv", { demo }, `ttq_bets_${demo ? "demo" : "actual"}.csv`);
    } catch (e) {
      setExportErr((e as Error).message);
    }
  };

  return (
    <div className="space-y-3">
      <PageHeader
        title="MY BETS"
        subtitle={`Ledger A — bets you placed yourself in Hard Rock Bet${demo ? " (DEMO ledger)" : ""}. Click a row for audit history.`}
        right={
          <>
            <button className="btn btn-primary" onClick={() => setManual(true)} data-testid="record-manual">
              Record a bet manually
            </button>
            <button className="btn" onClick={doExport}>
              Export CSV
            </button>
          </>
        }
      />
      <ErrorBox error={exportErr} />
      <Card
        title="Bets"
        right={
          <Tabs<SF>
            value={sf}
            onChange={setSf}
            options={[
              { value: "ALL", label: "All" },
              { value: "OPEN", label: "Open" },
              { value: "SETTLEMENT_REVIEW", label: "Review" },
              { value: "SETTLED", label: "Settled" },
            ]}
          />
        }
      >
        <ErrorBox error={error} onRetry={reload} />
        {loading && !data && <Loading />}
        {data && data.length === 0 && <Empty>No bets recorded{demo ? " in the DEMO ledger" : ""}.</Empty>}
        {data && data.length > 0 && (
          <TableWrap maxH="70vh">
            <table className="tbl" data-testid="bets-table">
              <thead>
                <tr>
                  <th className="r">#</th>
                  <th>Placed</th>
                  <th>Match</th>
                  <th>Match time</th>
                  <th>Selection</th>
                  <th>Market</th>
                  <th className="r">Line</th>
                  <th className="r">American</th>
                  <th className="r">Decimal</th>
                  <th className="r">Stake</th>
                  <th className="r">Payout</th>
                  <th className="r">Potential profit</th>
                  <th>Status</th>
                  <th className="r">Net</th>
                  <th className="r">Estimated EV</th>
                  <th className="r">CLV</th>
                  <th>Settled</th>
                  <th>Slip ref</th>
                  <th>Model v.</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {data.map((b) => (
                  <tr key={b.id} className="cursor-pointer" data-testid="bet-row" data-bet-id={b.id} onClick={() => setSelId(b.id)}>
                    <td className="r text-dim">{b.id}</td>
                    <td>
                      <Time iso={b.placed_at} />
                    </td>
                    <td>
                      {b.match} <DemoBadge show={b.is_demo} />
                    </td>
                    <td>
                      <Time iso={b.scheduled_at} />
                    </td>
                    <td className="font-medium">{b.player}</td>
                    <td>{marketLabel(b.market)}</td>
                    <td className="r">{b.line ?? "—"}</td>
                    <td className="r">{american(b.american)}</td>
                    <td className="r">{dec(b.decimal, 3)}</td>
                    <td className="r">
                      <Money v={b.stake} />
                    </td>
                    <td className="r">
                      <Money v={b.potential_payout} />
                    </td>
                    <td className="r">
                      <Money v={b.potential_profit} />
                    </td>
                    <td data-testid="bet-status">
                      <StatusBadge status={b.status} />
                    </td>
                    <td className="r">
                      <Money v={b.net} signed />
                    </td>
                    <td className="r">
                      <EvValue ev={b.ev} />
                    </td>
                    <td className="r">{signedPct(b.clv)}</td>
                    <td>
                      <Time iso={b.settled_at} />
                    </td>
                    <td className="text-sub">{b.bet_ref || "—"}</td>
                    <td className="text-sub">{b.model_version_id ?? "—"}</td>
                    <td className="max-w-[200px] truncate text-sub" title={b.notes || ""}>
                      {b.notes || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Card>

      {selId != null && <BetDrawer id={selId} onClose={() => setSelId(null)} onChanged={reload} />}
      <BetModal
        open={manual}
        onClose={() => {
          setManual(false);
          if (recorded.current) {
            recorded.current = false;
            reload();
          }
        }}
        onRecorded={() => {
          recorded.current = true;
        }}
      />
    </div>
  );
}

interface BetFull {
  id: number;
  recommendation_id: number | null;
  match_id: number;
  bookmaker_key: string;
  market: string;
  selection: string;
  line: number | null;
  accepted_american: number;
  accepted_decimal: number;
  stake: number;
  placed_at: string;
  bet_ref: string | null;
  notes: string | null;
  status: string;
  potential_payout: number;
  potential_profit: number;
  net_profit: number | null;
  settled_at: string | null;
  model_prob_at_placement: number | null;
  ev_at_placement: number | null;
  model_version_id: number | null;
  closing_decimal: number | null;
  clv: number | null;
  is_demo: boolean;
  created_at: string;
  updated_at: string | null;
}
interface BetDetail {
  bet: BetFull;
  match: MatchBrief;
  revisions: { id: number; changed_at: string; actor: string; reason: string; before: Record<string, unknown>; after: Record<string, unknown> }[];
  settlements: { id: number; created_at: string; proposed_status: string; proposed_net_profit: number | null; confidence: string; evidence: Record<string, unknown>; state: string; review_reason: string | null; applied_at: string | null }[];
}

function BetDrawer({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: () => void }) {
  const { data, error, loading, reload } = useApi<BetDetail>(`/api/bets/${id}`);
  const refresh = () => {
    reload();
    onChanged();
  };
  return (
    <Drawer open onClose={onClose} title={`Bet #${id}`}>
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data && <Loading />}
      {data && (
        <>
          <Card
            title={
              <span>
                {data.match.player1.name} vs {data.match.player2.name}
              </span>
            }
            right={
              <>
                <DemoBadge show={data.bet.is_demo} />
                <StatusBadge status={data.bet.status} />
              </>
            }
          >
            <div className="grid gap-x-6 text-xs sm:grid-cols-2">
              <div>
                <KV k="Sportsbook" v={data.bet.bookmaker_key === "hardrock" ? "Hard Rock Bet" : data.bet.bookmaker_key} />
                <KV k="Selection" v={data.bet.selection === "p1" ? data.match.player1.name : data.bet.selection === "p2" ? data.match.player2.name : data.bet.selection} />
                <KV k="Market" v={`${marketLabel(data.bet.market)}${data.bet.line != null ? ` ${data.bet.line}` : ""}`} />
                <KV k="Accepted odds" v={`${american(data.bet.accepted_american)} (${dec(data.bet.accepted_decimal, 3)})`} />
                <KV k="Stake" v={<Money v={data.bet.stake} />} />
                <KV k="Potential payout" v={<Money v={data.bet.potential_payout} />} />
                <KV k="Net profit" v={<Money v={data.bet.net_profit} signed />} />
              </div>
              <div>
                <KV k="Placed" v={<Time iso={data.bet.placed_at} />} />
                <KV k="Match time" v={<Time iso={data.match.scheduled_at} />} />
                <KV k="Settled" v={<Time iso={data.bet.settled_at} />} />
                <KV k="Model prob at placement" v={pct(data.bet.model_prob_at_placement)} />
                <KV k="Estimated EV at placement" v={<EvValue ev={data.bet.ev_at_placement} />} />
                <KV k="Closing decimal / CLV" v={`${dec(data.bet.closing_decimal)} / ${signedPct(data.bet.clv)}`} />
                <KV k="Slip ref" v={data.bet.bet_ref || "—"} />
              </div>
            </div>
            {data.bet.notes && <p className="mt-2 text-xs text-sub">Notes: {data.bet.notes}</p>}
          </Card>

          {data.bet.status === "SETTLEMENT_REVIEW" && <SettleForm id={id} onDone={refresh} />}
          <CorrectForm bet={data.bet} onDone={refresh} />

          <Card title={`Settlement proposals (${data.settlements.length})`}>
            {data.settlements.length === 0 ? (
              <Empty>No settlement proposals yet.</Empty>
            ) : (
              <TableWrap>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Created</th>
                      <th>Proposed</th>
                      <th className="r">Net</th>
                      <th>Confidence</th>
                      <th>State</th>
                      <th>Review reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.settlements.map((s) => (
                      <tr key={s.id}>
                        <td>
                          <Time iso={s.created_at} />
                        </td>
                        <td>
                          <StatusBadge status={s.proposed_status} />
                        </td>
                        <td className="r">
                          <Money v={s.proposed_net_profit} signed />
                        </td>
                        <td>{s.confidence}</td>
                        <td>{s.state}</td>
                        <td className="whitespace-normal text-sub">{s.review_reason || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            )}
          </Card>

          <Card title={`Revisions — audit history (${data.revisions.length})`}>
            {data.revisions.length === 0 ? (
              <Empty>No corrections recorded.</Empty>
            ) : (
              <ul className="space-y-2 text-xs">
                {data.revisions.map((r) => {
                  const keys = Object.keys(r.after || {}).filter((k) => JSON.stringify(r.after[k]) !== JSON.stringify(r.before?.[k]));
                  return (
                    <li key={r.id} className="rounded border border-line p-2">
                      <div className="flex flex-wrap justify-between gap-2 text-sub">
                        <span>
                          <Time iso={r.changed_at} /> · {r.actor}
                        </span>
                        <span className="italic">“{r.reason}”</span>
                      </div>
                      <ul className="mt-1 space-y-0.5">
                        {keys.map((k) => (
                          <li key={k} className="num">
                            <span className="text-sub">{k}:</span> {String(r.before?.[k] ?? "—")} → <b>{String(r.after[k] ?? "—")}</b>
                          </li>
                        ))}
                        {!keys.length && <li className="text-dim">No field differences recorded.</li>}
                      </ul>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </>
      )}
    </Drawer>
  );
}

function toLocalInput(iso: string) {
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function CorrectForm({ bet, onDone }: { bet: BetFull; onDone: () => void }) {
  const init = {
    accepted_american: String(bet.accepted_american),
    stake: String(bet.stake),
    placed_at: toLocalInput(bet.placed_at),
    bet_ref: bet.bet_ref || "",
    notes: bet.notes || "",
    selection: bet.selection,
    market: bet.market,
    line: bet.line != null ? String(bet.line) : "",
    status: bet.status,
  };
  const [f, setF] = useState(init);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "red" | "blue"; text: string } | null>(null);
  const set = (k: keyof typeof init) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMsg(null);
    const changes: Record<string, unknown> = {};
    if (f.accepted_american !== init.accepted_american) {
      const n = Number(f.accepted_american);
      if (!Number.isInteger(n) || (n > -100 && n < 100)) return setMsg({ tone: "red", text: "American odds must be ≤ -100 or ≥ +100." });
      changes.accepted_american = n;
    }
    if (f.stake !== init.stake) changes.stake = Number(f.stake);
    if (f.placed_at !== init.placed_at) changes.placed_at = localInputToIso(f.placed_at);
    if (f.bet_ref !== init.bet_ref) changes.bet_ref = f.bet_ref || null;
    if (f.notes !== init.notes) changes.notes = f.notes || null;
    if (f.selection !== init.selection) changes.selection = f.selection;
    if (f.market !== init.market) changes.market = f.market;
    if (f.line !== init.line) changes.line = f.line.trim() ? Number(f.line) : null;
    if (f.status !== init.status) changes.status = f.status;
    if (!Object.keys(changes).length) return setMsg({ tone: "red", text: "No changes to save." });
    if (reason.trim().length < 3) return setMsg({ tone: "red", text: "A correction reason (at least 3 characters) is required." });
    setBusy(true);
    try {
      await api(`/api/bets/${bet.id}`, { method: "PATCH", body: { changes, reason: reason.trim() } });
      setMsg({ tone: "blue", text: "Correction saved and added to the audit history." });
      setReason("");
      onDone();
    } catch (e2) {
      setMsg({ tone: "red", text: (e2 as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Correct bet">
      <form onSubmit={submit} className="space-y-2">
        <div className="grid gap-2 sm:grid-cols-3">
          <Field label="Accepted American">
            <input className="inp w-full num" value={f.accepted_american} onChange={set("accepted_american")} />
          </Field>
          <Field label="Stake USD">
            <input className="inp w-full num" value={f.stake} onChange={set("stake")} />
          </Field>
          <Field label="Placed at (local)">
            <input className="inp w-full num" type="datetime-local" value={f.placed_at} onChange={set("placed_at")} />
          </Field>
          <Field label="Market">
            <select className="inp w-full" value={f.market} onChange={set("market")}>
              {MARKETS.map((m) => (
                <option key={m} value={m}>
                  {marketLabel(m)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Selection">
            <input className="inp w-full" maxLength={16} value={f.selection} onChange={set("selection")} />
          </Field>
          <Field label="Line">
            <input className="inp w-full num" value={f.line} onChange={set("line")} />
          </Field>
          <Field label="Status">
            <select className="inp w-full" value={f.status} onChange={set("status")}>
              {["PLACED", "PENDING_RESULT", "WON", "LOST", "PUSH", "VOID", "SETTLEMENT_REVIEW"].map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Slip ref">
            <input className="inp w-full" value={f.bet_ref} onChange={set("bet_ref")} />
          </Field>
          <Field label="Notes">
            <input className="inp w-full" value={f.notes} onChange={set("notes")} />
          </Field>
        </div>
        <Field label="Reason for correction (required)">
          <input className="inp w-full" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. typo in accepted odds" required minLength={3} />
        </Field>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save correction"}
        </button>
        {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
      </form>
    </Card>
  );
}

function SettleForm({ id, onDone }: { id: number; onDone: () => void }) {
  const [result, setResult] = useState("WON");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api(`/api/bets/${id}/settle`, { body: { result, note: note || null } });
      onDone();
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Settle bet (manual review)">
      <form onSubmit={submit} className="space-y-2">
        <Notice tone="amber">This bet needs manual settlement. Confirm the result from an official source.</Notice>
        <div className="grid gap-2 sm:grid-cols-3">
          <Field label="Result">
            <select className="inp w-full" value={result} onChange={(e) => setResult(e.target.value)}>
              {["WON", "LOST", "PUSH", "VOID"].map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </Field>
          <Field label="Note" className="sm:col-span-2">
            <input className="inp w-full" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Source / evidence" />
          </Field>
        </div>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "Settling…" : "Settle"}
        </button>
        {err && <Notice tone="red">{err}</Notice>}
      </form>
    </Card>
  );
}


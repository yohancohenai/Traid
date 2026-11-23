"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { american, dec, marketLabel } from "@/lib/format";
import type { MatchBrief, MatchWithPred, Quote } from "@/lib/types";
import { MARKETS } from "./bet-modal";
import { Card, DemoBadge, FreshnessBadge, Field, Notice, TableWrap, Time } from "./ui";

interface Extra {
  market: string;
  selection: string;
  line: string;
  american: string;
}

const validAm = (s: string) => {
  const n = Number(s);
  return s.trim() !== "" && Number.isInteger(n) && (n <= -100 || n >= 100) && Math.abs(n) <= 100000;
};

/** FAST MANUAL HARD ROCK ENTRY — POST /api/odds/manual (array body). */
export function ManualOddsEntry({ fixedMatch, onStored }: { fixedMatch?: MatchBrief | null; onStored?: () => void }) {
  const { demo } = useApp();
  const [matches, setMatches] = useState<MatchWithPred[] | null>(null);
  const [matchId, setMatchId] = useState<number | "">(fixedMatch?.id ?? "");
  const [a1, setA1] = useState("");
  const [a2, setA2] = useState("");
  const [extras, setExtras] = useState<Extra[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<{ stored: Quote[]; warnings: string[] } | null>(null);

  useEffect(() => {
    if (fixedMatch) return;
    api<MatchWithPred[]>("/api/matches", { query: { demo, status: "SCHEDULED", days_back: 0, days_ahead: 3, limit: 300 } })
      .then(setMatches)
      .catch((e) => setErr((e as Error).message));
  }, [demo, fixedMatch]);

  const match: MatchBrief | null = fixedMatch || matches?.find((m) => m.id === matchId) || null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setRes(null);
    if (!match) return setErr("Pick a match.");
    const items: Record<string, unknown>[] = [];
    for (const [sel, v] of [
      ["p1", a1],
      ["p2", a2],
    ] as const) {
      if (v.trim() === "") continue;
      if (!validAm(v)) return setErr(`Invalid American odds for ${sel}: must be ≤ -100 or ≥ +100.`);
      items.push({ match_id: match.id, market: "match_winner", selection: sel, american: Number(v) });
    }
    for (const x of extras) {
      if (!x.american.trim() && !x.selection.trim()) continue;
      if (!validAm(x.american)) return setErr(`Invalid American odds in extra row (${x.market} ${x.selection}).`);
      if (!x.selection.trim()) return setErr("Extra rows need a selection.");
      items.push({ match_id: match.id, market: x.market, selection: x.selection.trim(), american: Number(x.american), line: x.line.trim() ? Number(x.line) : null });
    }
    if (!items.length) return setErr("Enter at least one price.");
    setBusy(true);
    try {
      const r = await api<{ stored: Quote[]; warnings: string[] }>("/api/odds/manual", { body: items });
      setRes(r);
      setA1("");
      setA2("");
      setExtras([]);
      onStored?.();
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Fast manual Hard Rock entry" testId="manual-entry">
      <form onSubmit={submit} className="space-y-3">
        <p className="text-[11px] text-dim">Type prices exactly as shown in the Hard Rock Bet app. Each quote is timestamped at entry.</p>
        {fixedMatch ? (
          <div className="flex items-center gap-1.5 text-xs">
            <span className="font-semibold">
              {fixedMatch.player1.name} vs {fixedMatch.player2.name}
            </span>
            <DemoBadge show={fixedMatch.is_demo} />
          </div>
        ) : (
          <Field label="Match">
            <select className="inp w-full" value={matchId} onChange={(e) => setMatchId(e.target.value ? Number(e.target.value) : "")} data-testid="manual-match">
              <option value="">{matches ? (matches.length ? "Select an upcoming match…" : "No upcoming matches") : "Loading…"}</option>
              {matches?.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.is_demo ? "[DEMO] " : ""}
                  {m.player1.name} vs {m.player2.name} — {new Date(m.scheduled_at).toLocaleString()}
                </option>
              ))}
            </select>
          </Field>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label={`${match?.player1.name || "Player 1"} (American)`}>
            <input className="inp w-full num" value={a1} onChange={(e) => setA1(e.target.value)} placeholder="-150" data-testid="manual-p1" />
          </Field>
          <Field label={`${match?.player2.name || "Player 2"} (American)`}>
            <input className="inp w-full num" value={a2} onChange={(e) => setA2(e.target.value)} placeholder="+125" data-testid="manual-p2" />
          </Field>
        </div>
        {extras.map((x, i) => (
          <div key={i} className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            <select className="inp" value={x.market} onChange={(e) => setExtras(extras.map((y, j) => (j === i ? { ...y, market: e.target.value } : y)))} aria-label="Market">
              {MARKETS.map((m) => (
                <option key={m} value={m}>
                  {marketLabel(m)}
                </option>
              ))}
            </select>
            <input className="inp" maxLength={16} placeholder="selection (p1, over…)" value={x.selection} onChange={(e) => setExtras(extras.map((y, j) => (j === i ? { ...y, selection: e.target.value } : y)))} aria-label="Selection" />
            <input className="inp num" placeholder="line" value={x.line} onChange={(e) => setExtras(extras.map((y, j) => (j === i ? { ...y, line: e.target.value } : y)))} aria-label="Line" />
            <input className="inp num" placeholder="American" value={x.american} onChange={(e) => setExtras(extras.map((y, j) => (j === i ? { ...y, american: e.target.value } : y)))} aria-label="American odds" />
            <button type="button" className="btn btn-ghost" onClick={() => setExtras(extras.filter((_, j) => j !== i))}>
              Remove
            </button>
          </div>
        ))}
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn btn-ghost" onClick={() => setExtras([...extras, { market: "set_handicap", selection: "p1", line: "", american: "" }])}>
            + Extra market row
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy || !match}>
            {busy ? "Saving…" : "Store Hard Rock quotes"}
          </button>
        </div>
        {err && <Notice tone="red">{err}</Notice>}
        {res && (
          <div className="space-y-2" data-testid="manual-result">
            {res.warnings.map((w) => (
              <Notice key={w} tone="amber">
                {w}
              </Notice>
            ))}
            <TableWrap>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Stored</th>
                    <th>Market</th>
                    <th>Selection</th>
                    <th className="r">American</th>
                    <th className="r">Decimal</th>
                    <th>Freshness</th>
                  </tr>
                </thead>
                <tbody>
                  {res.stored.map((q) => (
                    <tr key={q.id}>
                      <td>
                        <Time iso={q.captured_at} /> <DemoBadge show={q.is_demo} />
                      </td>
                      <td>{marketLabel(q.market)}</td>
                      <td>
                        {q.selection}
                        {q.line != null ? ` ${q.line}` : ""}
                      </td>
                      <td className="r">{american(q.american)}</td>
                      <td className="r">{dec(q.decimal, 3)}</td>
                      <td>
                        <FreshnessBadge status={q.freshness} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          </div>
        )}
      </form>
    </Card>
  );
}

/** Generic CSV upload card (multipart 'file'). */
export function CsvUpload({ title, path, help, testId }: { title: string; path: string; help: React.ReactNode; testId?: string }) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<Record<string, unknown> | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setErr(null);
    setRes(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      setRes(await api<Record<string, unknown>>(path, { method: "POST", form: fd }));
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title={title} testId={testId}>
      <form onSubmit={submit} className="space-y-2">
        <div className="text-[11px] text-dim">{help}</div>
        <input type="file" accept=".csv,text/csv" className="block w-full text-xs text-sub file:mr-2 file:rounded file:border file:border-line2 file:bg-panel2 file:px-2 file:py-1 file:text-ink" onChange={(e) => setFile(e.target.files?.[0] || null)} />
        <button className="btn" type="submit" disabled={!file || busy}>
          {busy ? "Uploading…" : "Upload CSV"}
        </button>
        {err && <Notice tone="red">{err}</Notice>}
        {res && (
          <Notice tone="blue">
            {Object.entries(res).map(([k, v]) => (
              <div key={k}>
                <b>{k}</b>: {typeof v === "object" ? JSON.stringify(v) : String(v)}
              </div>
            ))}
          </Notice>
        )}
      </form>
    </Card>
  );
}

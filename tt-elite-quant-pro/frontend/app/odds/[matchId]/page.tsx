"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo } from "react";
import { TimeLineChart } from "@/components/charts";
import { ManualOddsEntry } from "@/components/odds-entry";
import { Badge, Card, DemoBadge, DraftKingsNote, Empty, ErrorBox, EvValue, FreshnessBadge, KV, Loading, PageHeader, TableWrap, Time } from "@/components/ui";
import { american, dec, decimalToAmerican, marketLabel, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { MatchBrief, Prediction, Quote } from "@/lib/types";

interface Book {
  quotes: Record<string, Quote>;
  executable_in_fl: boolean;
  overround?: number;
  novig?: [number, number];
  novig_power?: [number, number];
  ev?: [number, number];
  opening: Record<string, number>;
}
interface OddsResp {
  match: MatchBrief;
  prediction: Prediction | null;
  books: Record<string, Book>;
  history: { at: string; book: string; sel: string; dec: number }[];
}

const BOOK_NAME: Record<string, string> = { hardrock: "Hard Rock Bet", draftkings: "DraftKings" };

export default function OddsDetailPage() {
  const { matchId } = useParams<{ matchId: string }>();
  const { data, error, loading, reload } = useApi<OddsResp>(`/api/odds/${encodeURIComponent(matchId)}`);

  const hist = useMemo(() => {
    if (!data) return [];
    const map = new Map<number, Record<string, number>>();
    for (const h of data.history) {
      const t = new Date(h.at).getTime();
      const row = map.get(t) || { t };
      row[`${h.book}_${h.sel}`] = h.dec;
      map.set(t, row);
    }
    return [...map.values()].sort((a, b) => a.t - b.t);
  }, [data]);

  if (loading && !data) return <Loading />;
  if (!data) return <ErrorBox error={error || "Match not found"} onRetry={reload} />;
  const m = data.match;
  const names = { p1: m.player1.name, p2: m.player2.name } as Record<string, string>;

  return (
    <div className="space-y-3">
      <PageHeader
        title={`ODDS — ${m.player1.name} vs ${m.player2.name}`}
        subtitle={
          <span className="inline-flex flex-wrap items-center gap-1.5">
            <Time iso={m.scheduled_at} /> · {m.status} <DemoBadge show={m.is_demo} />
          </span>
        }
        right={
          <>
            <Link className="btn btn-ghost" href="/odds">
              ← All matches
            </Link>
            <Link className="btn" href={`/matches/${m.id}`}>
              Match analysis
            </Link>
          </>
        }
      />

      {data.prediction && (
        <Card title="Model">
          <div className="grid gap-2 text-xs sm:grid-cols-2">
            <KV k={`${m.player1.name} model prob`} v={`${pct(data.prediction.p1_win)} · fair ${american(data.prediction.fair_p1.american)} (${dec(data.prediction.fair_p1.decimal)})`} />
            <KV k={`${m.player2.name} model prob`} v={`${pct(data.prediction.p2_win)} · fair ${american(data.prediction.fair_p2.american)} (${dec(data.prediction.fair_p2.decimal)})`} />
          </div>
        </Card>
      )}

      <div className="grid gap-3 lg:grid-cols-2">
        {(["hardrock", "draftkings"] as const).map((bk) => {
          const b = data.books[bk];
          if (!b) return null;
          return (
            <Card
              key={bk}
              testId={`book-${bk}`}
              title={BOOK_NAME[bk]}
              right={b.executable_in_fl ? <Badge tone="blue">Executable in Florida</Badge> : <DraftKingsNote />}
            >
              {Object.keys(b.quotes).length === 0 ? (
                <Empty>No quotes from {BOOK_NAME[bk]} for this match.</Empty>
              ) : (
                <div className="space-y-2 text-xs">
                  <TableWrap>
                    <table className="tbl">
                      <thead>
                        <tr>
                          <th>Selection</th>
                          <th className="r">Opening</th>
                          <th className="r">Current</th>
                          <th className="r">No-vig</th>
                          <th className="r">Estimated EV</th>
                          <th>Freshness</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(["p1", "p2"] as const).map((sel, i) => {
                          const q = b.quotes[sel];
                          const op = b.opening[sel];
                          return (
                            <tr key={sel}>
                              <td>{names[sel]}</td>
                              <td className="r">{op ? `${american(decimalToAmerican(op))} (${dec(op)})` : "—"}</td>
                              <td className="r font-medium">{q ? `${american(q.american)} (${dec(q.decimal)})` : "unavailable"}</td>
                              <td className="r">{b.novig ? pct(b.novig[i]) : "—"}</td>
                              <td className="r">{b.ev ? <EvValue ev={b.ev[i]} /> : "—"}</td>
                              <td>
                                <FreshnessBadge status={q?.freshness} />
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </TableWrap>
                  <KV k="Overround" v={pct(b.overround, 2)} />
                  <KV k="No-vig (power)" v={b.novig_power ? `${pct(b.novig_power[0])} / ${pct(b.novig_power[1])}` : "—"} />
                  {Object.values(b.quotes)
                    .filter((q) => q.market !== "match_winner" || q.line != null)
                    .map((q) => (
                      <KV key={q.id} k={`${marketLabel(q.market)} ${q.selection}${q.line != null ? ` ${q.line}` : ""}`} v={`${american(q.american)} (${dec(q.decimal)})`} />
                    ))}
                  <KV k="Last captured" v={<Time iso={b.quotes.p1?.captured_at || Object.values(b.quotes)[0]?.captured_at} />} />
                  {!b.executable_in_fl && <p className="text-[11px] text-dim">DraftKings prices are a market reference only. No bet can be recorded against them.</p>}
                </div>
              )}
            </Card>
          );
        })}
      </div>

      <Card title="Price history (decimal, match winner)">
        <TimeLineChart
          data={hist}
          lines={[
            { key: "hardrock_p1", name: `HR ${m.player1.name}`, color: "#38bdf8" },
            { key: "hardrock_p2", name: `HR ${m.player2.name}`, color: "#a78bfa" },
            { key: "draftkings_p1", name: `DK ${m.player1.name} (ref)`, color: "#38bdf8", dashed: true },
            { key: "draftkings_p2", name: `DK ${m.player2.name} (ref)`, color: "#a78bfa", dashed: true },
          ]}
          height={260}
          yFmt={(v) => v.toFixed(2)}
          step
        />
      </Card>

      <ManualOddsEntry fixedMatch={m} onStored={reload} />
    </div>
  );
}

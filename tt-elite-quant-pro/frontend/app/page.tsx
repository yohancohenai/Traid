"use client";

import Link from "next/link";
import { useApp } from "@/lib/app-context";
import { american, agoFromIso, dec, pct, signClass, usd } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { MatchBrief, MatchWithPred, Recommendation } from "@/lib/types";
import { Card, DemoBadge, Empty, ErrorBox, EvValue, FreshnessBadge, Kpi, Loading, PageHeader, ProbCI, StatusBadge, TableWrap, Time } from "@/components/ui";

interface Overview {
  is_demo: boolean;
  now: string;
  next_matches: MatchWithPred[];
  opportunities: Recommendation[];
  no_qualifying: boolean;
  recent_matches: MatchBrief[];
  pending_bets: { id: number; market: string; selection: string; stake: number; accepted_american: number; accepted_decimal: number; placed_at: string; status: string; is_demo: boolean; match: MatchBrief }[];
  pl: { net_pl: number; roi: number | null; total_bets: number; pending: number; bankroll: number; total_wagered: number; win_pct: number | null };
  model: { status: string; champion: string | null; recent_log_loss: number | null; reference_log_loss: number | null; recent_brier: number | null; recent_accuracy: number | null; n: number | null; source: string | null };
  sources: { key: string; name: string; status: string; last_success_at: string | null }[];
  latest_odds: { hardrock: string | null; draftkings: string | null };
}

export default function OverviewPage() {
  const { demo } = useApp();
  const { data, error, loading, reload } = useApi<Overview>("/api/overview", { demo });

  return (
    <div>
      <PageHeader title="OVERVIEW" subtitle="Next matches, qualifying opportunities, model health and your ledger at a glance." right={<button className="btn btn-ghost" onClick={reload}>Refresh</button>} />
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data && <Loading />}
      {data && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
            <Kpi label="Bankroll" value={usd(data.pl.bankroll)} />
            <Kpi label="Realized P/L" value={usd(data.pl.net_pl, true)} valueClass={signClass(data.pl.net_pl)} />
            <Kpi label="ROI" value={pct(data.pl.roi)} valueClass={signClass(data.pl.roi)} />
            <Kpi label="Total bets" value={data.pl.total_bets} sub={`Wagered ${usd(data.pl.total_wagered)}`} />
            <Kpi label="Pending bets" value={data.pl.pending} />
            <Kpi label="Win %" value={pct(data.pl.win_pct)} />
          </div>

          <div className="grid gap-3 xl:grid-cols-3">
            <Card
              className="xl:col-span-2"
              title="Qualifying opportunities"
              right={
                <Link className="text-[11px] text-accent hover:underline" href="/opportunities">
                  All opportunities →
                </Link>
              }
            >
              {data.no_qualifying || data.opportunities.length === 0 ? (
                <div className="py-6 text-center text-sm font-bold tracking-wider text-sub" data-testid="no-qualifying">
                  NO QUALIFYING BETS FOUND.
                </div>
              ) : (
                <TableWrap>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Match</th>
                        <th>Selection</th>
                        <th className="r">Hard Rock</th>
                        <th>Quote</th>
                        <th className="r">Est. win prob</th>
                        <th className="r">Estimated EV</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.opportunities.map((r) => (
                        <tr key={r.id}>
                          <td>
                            <Link className="hover:text-accent" href={`/matches/${r.match.id}`}>
                              {r.match.player1.name} vs {r.match.player2.name}
                            </Link>{" "}
                            <DemoBadge show={r.is_demo} />
                            <div className="text-[11px] text-dim">
                              <Time iso={r.match.scheduled_at} />
                            </div>
                          </td>
                          <td>{r.selection_name}</td>
                          <td className="r num">
                            {american(r.american_odds)} <span className="text-dim">({dec(r.decimal_odds)})</span>
                          </td>
                          <td>
                            <FreshnessBadge status={r.quote_status} />
                          </td>
                          <td className="r">
                            <ProbCI p={r.model_prob} ci={r.prob_interval} />
                          </td>
                          <td className="r">
                            <EvValue ev={r.ev} />
                          </td>
                          <td>
                            <StatusBadge status={r.status} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              )}
            </Card>

            <Card title="Model health" right={<StatusBadge status={data.model.status} />}>
              <dl className="space-y-1 text-xs">
                <Row k="Champion" v={data.model.champion || "—"} />
                <Row k="Recent log loss" v={dec(data.model.recent_log_loss, 4)} />
                <Row k="Reference log loss" v={dec(data.model.reference_log_loss, 4)} />
                <Row k="Recent Brier" v={dec(data.model.recent_brier, 4)} />
                <Row k="Recent accuracy" v={pct(data.model.recent_accuracy)} />
                <Row k="Sample" v={data.model.n ?? "—"} />
                <Row k="Source" v={data.model.source || "—"} />
              </dl>
              <Link className="mt-2 inline-block text-[11px] text-accent hover:underline" href="/models">
                Model performance →
              </Link>
            </Card>
          </div>

          <Card title="Next matches" right={<Link className="text-[11px] text-accent hover:underline" href="/matches">All matches →</Link>}>
            {data.next_matches.length === 0 ? (
              <Empty>No upcoming matches{data.is_demo ? "" : " in LIVE data"}.</Empty>
            ) : (
              <TableWrap>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Match</th>
                      <th className="r">Model P1 [CI]</th>
                      <th className="r">Model P2</th>
                      <th className="r">Hard Rock P1</th>
                      <th className="r">Hard Rock P2</th>
                      <th>Quote</th>
                      <th>Quality</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.next_matches.map((m) => (
                      <tr key={m.id}>
                        <td>
                          <Time iso={m.scheduled_at} />
                        </td>
                        <td>
                          <Link className="hover:text-accent" href={`/matches/${m.id}`}>
                            {m.player1.name} vs {m.player2.name}
                          </Link>{" "}
                          <DemoBadge show={m.is_demo} />
                        </td>
                        <td className="r">{m.prediction ? <ProbCI p={m.prediction.p1_win} ci={m.prediction.p1_ci} /> : "—"}</td>
                        <td className="r num">{m.prediction ? pct(1 - m.prediction.p1_win) : "—"}</td>
                        <td className="r num">{m.hardrock?.p1 ? american(m.hardrock.p1.american) : "—"}</td>
                        <td className="r num">{m.hardrock?.p2 ? american(m.hardrock.p2.american) : "—"}</td>
                        <td>
                          <FreshnessBadge status={m.hardrock?.p1?.freshness || "UNAVAILABLE"} />
                        </td>
                        <td>{m.prediction?.data_quality || m.data_quality || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            )}
          </Card>

          <div className="grid gap-3 lg:grid-cols-2">
            <Card title="Pending bets" right={<Link className="text-[11px] text-accent hover:underline" href="/bets">My bets →</Link>}>
              {data.pending_bets.length === 0 ? (
                <Empty>No pending bets.</Empty>
              ) : (
                <TableWrap>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Placed</th>
                        <th>Match</th>
                        <th>Sel.</th>
                        <th className="r">Odds</th>
                        <th className="r">Stake</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.pending_bets.map((b) => (
                        <tr key={b.id}>
                          <td>
                            <Time iso={b.placed_at} />
                          </td>
                          <td>
                            {b.match.player1.name} vs {b.match.player2.name} <DemoBadge show={b.is_demo} />
                          </td>
                          <td>{b.selection === "p1" ? b.match.player1.name : b.selection === "p2" ? b.match.player2.name : b.selection}</td>
                          <td className="r num">{american(b.accepted_american)}</td>
                          <td className="r num">{usd(b.stake)}</td>
                          <td>
                            <StatusBadge status={b.status} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              )}
            </Card>

            <Card title="Recent completed matches">
              {data.recent_matches.length === 0 ? (
                <Empty>No completed matches.</Empty>
              ) : (
                <TableWrap>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Finished</th>
                        <th>Match</th>
                        <th className="r">Sets</th>
                        <th>Status</th>
                        <th>Result</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.recent_matches.map((m) => (
                        <tr key={m.id}>
                          <td>
                            <Time iso={m.finished_at || m.scheduled_at} />
                          </td>
                          <td>
                            <Link className="hover:text-accent" href={`/matches/${m.id}`}>
                              {m.player1.name} vs {m.player2.name}
                            </Link>{" "}
                            <DemoBadge show={m.is_demo} />
                          </td>
                          <td className="r num">
                            {m.sets_p1 ?? "—"}-{m.sets_p2 ?? "—"}
                          </td>
                          <td>{m.status}</td>
                          <td className="text-[11px] text-sub">{m.result_verified ? "verified" : "unverified"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              )}
            </Card>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <Card title="Data feed status" right={<Link className="text-[11px] text-accent hover:underline" href="/sources">Sources →</Link>}>
              {data.sources.length === 0 ? (
                <Empty>No data sources have run in this mode.</Empty>
              ) : (
                <TableWrap>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Source</th>
                        <th>Status</th>
                        <th>Last success</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.sources.map((s) => (
                        <tr key={s.key}>
                          <td>{s.name}</td>
                          <td>
                            <StatusBadge status={s.status} />
                          </td>
                          <td>
                            <Time iso={s.last_success_at} /> <span className="text-[11px] text-dim">({agoFromIso(s.last_success_at)})</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              )}
            </Card>
            <Card title="Latest odds captured">
              <dl className="space-y-1 text-xs">
                <Row
                  k="Hard Rock Bet"
                  v={
                    <>
                      <Time iso={data.latest_odds.hardrock} /> <span className="text-dim">({agoFromIso(data.latest_odds.hardrock)})</span>
                    </>
                  }
                />
                <Row
                  k={
                    <>
                      DraftKings <span className="text-[10px] text-dim">(Reference only — not executable in Florida)</span>
                    </>
                  }
                  v={
                    <>
                      <Time iso={data.latest_odds.draftkings} /> <span className="text-dim">({agoFromIso(data.latest_odds.draftkings)})</span>
                    </>
                  }
                />
              </dl>
              <p className="mt-2 text-[11px] text-dim">Individual quotes are marked VERIFIED only while within the maximum quote age.</p>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ k, v }: { k: React.ReactNode; v: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line/60 py-1 last:border-0">
      <dt className="text-sub">{k}</dt>
      <dd className="num text-right">{v}</dd>
    </div>
  );
}

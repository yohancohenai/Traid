"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";
import { BetModal, type BetPrefill } from "@/components/bet-modal";
import { ScorelineChart, TimeLineChart, withT } from "@/components/charts";
import { OpportunityCard, recToPrefill } from "@/components/opportunity-card";
import { Badge, Card, DemoBadge, DraftKingsNote, Empty, ErrorBox, FreshnessBadge, KV, Loading, PageHeader, StatusBadge, TableWrap, Time, cx } from "@/components/ui";
import { american, dec, isNum, marketLabel, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { MatchBrief, Prediction, Quote, Recommendation } from "@/lib/types";

interface Detail {
  match: MatchBrief;
  prediction: Prediction | null;
  model: string | null;
  prediction_history: { at: string; p1_win: number }[];
  derived_markets: {
    p_game: number;
    p_point: number;
    scorelines: Record<string, number>;
    set_handicap: Record<string, number>;
    total_points: Record<string, number>;
    point_handicap: Record<string, number>;
    points_markets_status: string;
    assumptions: string;
  } | null;
  quotes: Quote[];
  h2h: MatchBrief[];
  recent: { p1: FormRow[]; p2: FormRow[] };
  recommendations: Recommendation[];
}
interface FormRow {
  id: number;
  at: string;
  won: boolean;
  opponent: string;
  score: string;
}

export default function MatchDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, loading, reload } = useApi<Detail>(`/api/matches/${encodeURIComponent(id)}`);
  const [prefill, setPrefill] = useState<BetPrefill | null>(null);
  const recorded = useRef(false);

  if (loading && !data) return <Loading />;
  if (!data) return <ErrorBox error={error || "Match not found"} onRetry={reload} />;
  const { match: m, prediction: p, derived_markets: dm } = data;
  const comps = p?.components || {};
  const compVals = Object.values(comps);
  const spread = compVals.length ? Math.max(...compVals) - Math.min(...compVals) : null;

  return (
    <div className="space-y-3">
      <PageHeader
        title={`${m.player1.name} vs ${m.player2.name}`}
        subtitle={
          <span className="inline-flex flex-wrap items-center gap-1.5">
            <Time iso={m.scheduled_at} /> · {m.competition || "TT Elite Series"} {m.tournament ? `· ${m.tournament}` : ""} · <StatusBadge status={m.status} />
            {m.sets_p1 != null && <span className="num">Sets {m.sets_p1}-{m.sets_p2}</span>}
            <DemoBadge show={m.is_demo} />
          </span>
        }
        right={
          <Link className="btn" href={`/odds/${m.id}`}>
            Odds comparison →
          </Link>
        }
      />

      <div className="grid gap-3 lg:grid-cols-3">
        <Card title="Prediction" right={data.model ? <span className="text-[10px] text-dim">{data.model}</span> : null}>
          {!p ? (
            <Empty>No prediction for this match yet.</Empty>
          ) : (
            <div className="text-xs">
              <div className="mb-2 grid grid-cols-2 gap-2">
                <div className="rounded-md bg-panel2 p-2">
                  <div className="truncate text-[11px] text-sub">{m.player1.name}</div>
                  <div className="num text-xl font-semibold">{pct(p.p1_win)}</div>
                  <div className="num text-[11px] text-dim">
                    CI {pct(p.p1_ci[0])} – {pct(p.p1_ci[1])}
                  </div>
                </div>
                <div className="rounded-md bg-panel2 p-2">
                  <div className="truncate text-[11px] text-sub">{m.player2.name}</div>
                  <div className="num text-xl font-semibold">{pct(p.p2_win)}</div>
                  <div className="num text-[11px] text-dim">
                    CI {pct(1 - p.p1_ci[1])} – {pct(1 - p.p1_ci[0])}
                  </div>
                </div>
              </div>
              <KV k={`Fair odds ${m.player1.name}`} v={`${american(p.fair_p1.american)} · ${dec(p.fair_p1.decimal, 3)}`} />
              <KV k={`Fair odds ${m.player2.name}`} v={`${american(p.fair_p2.american)} · ${dec(p.fair_p2.decimal, 3)}`} />
              <KV k="Game (set) win prob P1" v={pct(p.p_game)} />
              <KV k="Data quality" v={p.data_quality} />
              <KV k="As of" v={<Time iso={p.as_of} />} />
            </div>
          )}
        </Card>

        <Card title="Component models (agreement)" right={isNum(spread) ? <span className="num text-[11px] text-sub">spread {pct(spread)}</span> : null}>
          {compVals.length === 0 ? (
            <Empty>No component probabilities.</Empty>
          ) : (
            <div className="space-y-1.5 text-xs">
              {Object.entries(comps).map(([k, v]) => (
                <div key={k}>
                  <div className="flex justify-between">
                    <span className="text-sub">{k}</span>
                    <span className="num">{pct(v)}</span>
                  </div>
                  <div className="h-1.5 rounded bg-panel2">
                    <div className="h-1.5 rounded bg-sky-500/70" style={{ width: `${Math.max(0, Math.min(1, v)) * 100}%` }} />
                  </div>
                </div>
              ))}
              <p className="pt-1 text-[11px] text-dim">P1 win probability per component. Wide spread = lower agreement.</p>
            </div>
          )}
        </Card>

        <Card title="Scoreline distribution (P1 perspective)">
          <ScorelineChart scorelines={p?.scorelines || dm?.scorelines} />
        </Card>
      </div>

      {dm && (
        <Card title="Derived markets" right={<Badge tone={dm.points_markets_status.startsWith("EXPERIMENTAL") ? "amber" : "gray"}>Points markets: {dm.points_markets_status}</Badge>}>
          <div className="grid gap-3 text-xs md:grid-cols-3">
            <DerivedTable title={`Set handicap — ${m.player1.name}`} rows={dm.set_handicap} label={(k) => `${m.player1.name.split(" ")[0]} ${k} sets`} status="Derived from scoreline distribution" />
            <DerivedTable title="Total points — over" rows={dm.total_points} label={(k) => `Over ${k}`} status={dm.points_markets_status} />
            <DerivedTable title={`Point handicap — ${m.player1.name}`} rows={dm.point_handicap} label={(k) => `${m.player1.name.split(" ")[0]} ${k} pts`} status={dm.points_markets_status} />
          </div>
          <p className="mt-2 text-[11px] text-dim">
            Game p {pct(dm.p_game)} · point p {pct(dm.p_point)}. {dm.assumptions}
          </p>
        </Card>
      )}

      {data.recommendations.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-sub">Recommendations</h2>
          <div className="grid gap-3 xl:grid-cols-2">
            {data.recommendations.map((r) => (
              <OpportunityCard key={r.id} r={r} onBet={(x) => setPrefill(recToPrefill(x))} />
            ))}
          </div>
        </div>
      )}

      <Card title="Quotes" right={<Link className="text-[11px] text-accent hover:underline" href={`/odds/${m.id}`}>Compare books →</Link>}>
        {data.quotes.length === 0 ? (
          <Empty>No odds quotes captured for this match.</Empty>
        ) : (
          <TableWrap maxH="360px">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Captured</th>
                  <th>Book</th>
                  <th>Market</th>
                  <th>Selection</th>
                  <th className="r">American</th>
                  <th className="r">Decimal</th>
                  <th>Freshness</th>
                  <th>Source</th>
                  <th>Availability</th>
                </tr>
              </thead>
              <tbody>
                {[...data.quotes].reverse().map((q) => (
                  <tr key={q.id}>
                    <td>
                      <Time iso={q.captured_at} /> <DemoBadge show={q.is_demo} />
                    </td>
                    <td>
                      {q.bookmaker === "hardrock" ? "Hard Rock Bet" : q.bookmaker === "draftkings" ? "DraftKings" : q.bookmaker}{" "}
                      {q.bookmaker === "draftkings" && <DraftKingsNote />}
                    </td>
                    <td>{marketLabel(q.market)}</td>
                    <td>
                      {q.selection === "p1" ? m.player1.name : q.selection === "p2" ? m.player2.name : q.selection}
                      {q.line != null ? ` ${q.line}` : ""}
                    </td>
                    <td className="r">{american(q.american)}</td>
                    <td className="r">{dec(q.decimal, 3)}</td>
                    <td>
                      <FreshnessBadge status={q.freshness} />
                    </td>
                    <td className="text-sub">{q.source}</td>
                    <td className="text-sub">{q.availability}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Card>

      <div className="grid gap-3 lg:grid-cols-3">
        <Card title="Prediction history (P1 win)">
          <TimeLineChart data={withT(data.prediction_history)} lines={[{ key: "p1_win", name: "P1 win" }]} height={180} yFmt={(v) => `${(v * 100).toFixed(0)}%`} step />
        </Card>
        <FormCard title={`Recent form — ${m.player1.name}`} rows={data.recent.p1} />
        <FormCard title={`Recent form — ${m.player2.name}`} rows={data.recent.p2} />
      </div>

      <Card title={`Head to head (${data.h2h.length})`}>
        {data.h2h.length === 0 ? (
          <Empty>No previous meetings.</Empty>
        ) : (
          <TableWrap>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Match</th>
                  <th className="r">Sets</th>
                  <th>Set scores</th>
                </tr>
              </thead>
              <tbody>
                {data.h2h.map((x) => (
                  <tr key={x.id}>
                    <td>
                      <Time iso={x.scheduled_at} />
                    </td>
                    <td>
                      <Link className="hover:text-accent" href={`/matches/${x.id}`}>
                        {x.player1.name} vs {x.player2.name}
                      </Link>{" "}
                      <DemoBadge show={x.is_demo} />
                    </td>
                    <td className="r num">
                      {x.sets_p1}-{x.sets_p2}
                    </td>
                    <td className="num text-sub">{x.set_scores.map((s) => s.join("-")).join(", ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Card>

      <BetModal
        open={!!prefill}
        prefill={prefill}
        onClose={() => {
          setPrefill(null);
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

function DerivedTable({ title, rows, label, status }: { title: string; rows: Record<string, number>; label: (k: string) => string; status: string }) {
  return (
    <div className="min-w-0">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="truncate font-semibold">{title}</span>
      </div>
      <table className="tbl">
        <thead>
          <tr>
            <th>Line</th>
            <th className="r">Prob</th>
            <th className="r">Fair</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(rows).map(([k, v]) => (
            <tr key={k}>
              <td>{label(k)}</td>
              <td className="r">{pct(v)}</td>
              <td className="r">{v > 0 && v < 1 ? dec(1 / v) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-1 text-[10px] text-dim">{status}</div>
    </div>
  );
}

function FormCard({ title, rows }: { title: string; rows: FormRow[] }) {
  const w = rows.filter((r) => r.won).length;
  return (
    <Card title={title} right={<span className="num text-[11px] text-sub">{w}-{rows.length - w}</span>}>
      {rows.length === 0 ? (
        <Empty>No previous matches.</Empty>
      ) : (
        <TableWrap>
          <table className="tbl">
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Time iso={r.at} dateOnly />
                  </td>
                  <td>
                    <span className={cx("font-bold", r.won ? "text-ink" : "text-dim")}>{r.won ? "W" : "L"}</span>
                  </td>
                  <td className="num">{r.score}</td>
                  <td className="truncate">vs {r.opponent}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
    </Card>
  );
}

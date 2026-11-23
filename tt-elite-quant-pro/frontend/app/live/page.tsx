"use client";

import Link from "next/link";
import { Badge, Card, DemoBadge, Empty, ErrorBox, Loading, Notice, PageHeader, Time } from "@/components/ui";
import { useApp } from "@/lib/app-context";
import { ago, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { MatchBrief } from "@/lib/types";

interface LiveItem extends MatchBrief {
  feed_status: "LIVE" | "DELAYED" | "STALE" | "UNAVAILABLE";
  feed_age_seconds: number | null;
  live_p1_win?: number;
  pre_match_p1_win?: number;
  live_note?: string;
}

const FEED_TONE: Record<string, string> = { LIVE: "blue", DELAYED: "amber", STALE: "amber", UNAVAILABLE: "gray" };

export default function LivePage() {
  const { demo } = useApp();
  const { data, error, loading, reload } = useApi<{ items: LiveItem[]; live_odds: string; note: string }>("/api/live", { demo }, { intervalMs: 15_000 });

  return (
    <div>
      <PageHeader title="LIVE MATCHES" subtitle="Auto-refreshes every 15 seconds. Scores are labelled by feed age." right={<button className="btn btn-ghost" onClick={reload}>Refresh now</button>} />
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data && <Loading />}
      {data && (
        <div className="space-y-3">
          <Notice tone="gray">
            Live odds: <b>{data.live_odds}</b>. {data.note}
          </Notice>
          {data.items.length === 0 && (
            <Card>
              <Empty>No matches are in progress{demo ? " in DEMO data" : ""}.</Empty>
            </Card>
          )}
          <div className="grid gap-3 lg:grid-cols-2">
            {data.items.map((m) => {
              const sets = m.live_state?.sets || [m.sets_p1 ?? 0, m.sets_p2 ?? 0];
              const pts = m.live_state?.points || [0, 0];
              return (
                <Card
                  key={m.id}
                  title={
                    <Link href={`/matches/${m.id}`} className="hover:text-accent">
                      {m.player1.name} vs {m.player2.name}
                    </Link>
                  }
                  right={
                    <>
                      <DemoBadge show={m.is_demo} />
                      <Badge tone={FEED_TONE[m.feed_status] || "gray"} title={`Feed age ${ago(m.feed_age_seconds)}`}>
                        {m.feed_status}
                      </Badge>
                    </>
                  }
                >
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div>
                      <div className="lbl">Sets</div>
                      <div className="num text-2xl font-semibold">
                        {sets[0]}-{sets[1]}
                      </div>
                    </div>
                    <div>
                      <div className="lbl">Points</div>
                      <div className="num text-2xl font-semibold">
                        {pts[0]}-{pts[1]}
                      </div>
                    </div>
                    <div>
                      <div className="lbl">Feed age</div>
                      <div className="num text-sm">{ago(m.feed_age_seconds)}</div>
                      <div className="text-[10px] text-dim">
                        <Time iso={m.live_updated_at} timeOnly />
                      </div>
                    </div>
                  </div>
                  {m.set_scores.length > 0 && <div className="num mt-2 text-center text-[11px] text-sub">Completed sets: {m.set_scores.map((s) => s.join("-")).join(", ")}</div>}
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                    <div className="rounded bg-panel2 p-2">
                      <div className="lbl">In-play estimate P1</div>
                      <div className="num text-lg font-semibold">{pct(m.live_p1_win)}</div>
                    </div>
                    <div className="rounded bg-panel2 p-2">
                      <div className="lbl">Pre-match P1</div>
                      <div className="num text-lg font-semibold">{pct(m.pre_match_p1_win)}</div>
                    </div>
                  </div>
                  {m.live_note && <p className="mt-2 text-[11px] text-dim">{m.live_note}</p>}
                </Card>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

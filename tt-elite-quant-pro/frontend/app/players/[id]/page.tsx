"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo } from "react";
import { TimeLineChart } from "@/components/charts";
import { Card, DemoBadge, Empty, ErrorBox, Loading, PageHeader, TableWrap, Time } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import type { MatchBrief } from "@/lib/types";

interface PlayerDetail {
  id: number;
  name: string;
  is_demo: boolean;
  aliases: { alias: string; source: string; how: string }[];
  rating_history: Record<"elo" | "glicko2" | "bayes", { at: string; rating: number; unc: number | null }[]>;
  recent: MatchBrief[];
}

export default function PlayerDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, loading, reload } = useApi<PlayerDetail>(`/api/players/${encodeURIComponent(id)}`);

  const series = useMemo(() => {
    if (!data) return [];
    const map = new Map<number, Record<string, number>>();
    for (const model of ["elo", "glicko2", "bayes"] as const) {
      for (const r of data.rating_history[model] || []) {
        const t = new Date(r.at).getTime();
        const row = map.get(t) || { t };
        row[model] = r.rating;
        map.set(t, row);
      }
    }
    return [...map.values()].sort((a, b) => a.t - b.t);
  }, [data]);

  if (loading && !data) return <Loading />;
  if (!data) return <ErrorBox error={error || "Player not found"} onRetry={reload} />;
  const pid = data.id;

  return (
    <div className="space-y-3">
      <PageHeader title={data.name} subtitle={<span className="inline-flex items-center gap-1.5">Player #{data.id} <DemoBadge show={data.is_demo} /></span>} right={<Link className="btn btn-ghost" href="/players">← Ratings</Link>} />
      <Card title="Rating history (Elo · Glicko-2 · Bayes)">
        <TimeLineChart
          data={series}
          lines={[
            { key: "elo", name: "Elo" },
            { key: "glicko2", name: "Glicko-2" },
            { key: "bayes", name: "Bayes" },
          ]}
          height={300}
          yFmt={(v) => v.toFixed(0)}
        />
      </Card>
      <div className="grid gap-3 lg:grid-cols-3">
        <Card title="Aliases">
          {data.aliases.length === 0 ? (
            <Empty>No aliases.</Empty>
          ) : (
            <TableWrap>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Alias</th>
                    <th>Source</th>
                    <th>Linked by</th>
                  </tr>
                </thead>
                <tbody>
                  {data.aliases.map((a, i) => (
                    <tr key={i}>
                      <td>{a.alias}</td>
                      <td className="text-sub">{a.source}</td>
                      <td className="text-sub">{a.how}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          )}
        </Card>
        <Card title="Recent matches" className="lg:col-span-2">
          {data.recent.length === 0 ? (
            <Empty>No finished matches.</Empty>
          ) : (
            <TableWrap maxH="420px">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Opponent</th>
                    <th>Result</th>
                    <th className="r">Sets</th>
                    <th>Set scores</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent.map((m) => {
                    const isP1 = m.player1.id === pid;
                    const my = isP1 ? m.sets_p1 : m.sets_p2;
                    const op = isP1 ? m.sets_p2 : m.sets_p1;
                    const won = (my ?? 0) > (op ?? 0);
                    return (
                      <tr key={m.id}>
                        <td>
                          <Time iso={m.scheduled_at} />
                        </td>
                        <td>
                          <Link className="hover:text-accent" href={`/matches/${m.id}`}>
                            {isP1 ? m.player2.name : m.player1.name}
                          </Link>{" "}
                          <DemoBadge show={m.is_demo} />
                        </td>
                        <td className={won ? "font-bold" : "text-dim"}>{won ? "W" : "L"}</td>
                        <td className="r num">
                          {my}-{op}
                        </td>
                        <td className="num text-sub">{m.set_scores.map((s) => (isP1 ? s : [s[1], s[0]]).join("-")).join(", ") || "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </TableWrap>
          )}
        </Card>
      </div>
    </div>
  );
}

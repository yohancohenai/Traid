"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Card, DemoBadge, Empty, ErrorBox, FreshnessBadge, Loading, PageHeader, ProbCI, StatusBadge, TableWrap, Time } from "@/components/ui";
import { useApp } from "@/lib/app-context";
import { american, dec, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { MatchWithPred, Quote } from "@/lib/types";

const STATUSES = ["", "SCHEDULED", "LIVE", "FINISHED", "RETIRED", "CANCELLED"];

function Price({ q }: { q?: Quote }) {
  if (!q) return <span className="text-dim">unavailable</span>;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="num font-medium">{american(q.american)}</span>
      <span className="num text-[11px] text-dim">{dec(q.decimal)}</span>
      <FreshnessBadge status={q.freshness} title={`Captured ${q.captured_at}`} />
    </span>
  );
}

export default function MatchesPage() {
  const { demo } = useApp();
  const router = useRouter();
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("SCHEDULED");
  const [daysBack, setDaysBack] = useState(0);
  const [daysAhead, setDaysAhead] = useState(2);

  useEffect(() => {
    const t = setTimeout(() => setQ(qInput.trim()), 300);
    return () => clearTimeout(t);
  }, [qInput]);

  const { data, error, loading, reload } = useApi<MatchWithPred[]>("/api/matches", { demo, q, status, days_back: daysBack, days_ahead: daysAhead, limit: 300 });

  return (
    <div>
      <PageHeader title="UPCOMING MATCHES" subtitle="Model probabilities with uncertainty and current Hard Rock Bet prices. Click a row for full analysis." />
      <Card
        title="Matches"
        right={
          <div className="flex flex-wrap items-center gap-2">
            <input className="inp w-44" placeholder="Search player…" value={qInput} onChange={(e) => setQInput(e.target.value)} aria-label="Search player" />
            <select className="inp" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status filter">
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s || "All statuses"}
                </option>
              ))}
            </select>
            <select className="inp" value={daysBack} onChange={(e) => setDaysBack(Number(e.target.value))} aria-label="Days back">
              {[0, 1, 3, 7].map((d) => (
                <option key={d} value={d}>
                  {d}d back
                </option>
              ))}
            </select>
            <select className="inp" value={daysAhead} onChange={(e) => setDaysAhead(Number(e.target.value))} aria-label="Days ahead">
              {[1, 2, 3, 7].map((d) => (
                <option key={d} value={d}>
                  {d}d ahead
                </option>
              ))}
            </select>
          </div>
        }
      >
        <ErrorBox error={error} onRetry={reload} />
        {loading && !data && <Loading />}
        {data && data.length === 0 && <Empty>No matches for these filters{demo ? "" : " in LIVE data"}.</Empty>}
        {data && data.length > 0 && (
          <TableWrap maxH="70vh">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Players</th>
                  <th>Status</th>
                  <th className="r">Model P1 [CI]</th>
                  <th className="r">Model P2</th>
                  <th>Hard Rock P1</th>
                  <th>Hard Rock P2</th>
                  <th>Data quality</th>
                </tr>
              </thead>
              <tbody>
                {data.map((m) => (
                  <tr key={m.id} className="cursor-pointer" data-testid="match-row" onClick={() => router.push(`/matches/${m.id}`)}>
                    <td>
                      <Time iso={m.scheduled_at} />
                    </td>
                    <td>
                      <span className="font-medium">{m.player1.name}</span> <span className="text-dim">vs</span> <span className="font-medium">{m.player2.name}</span> <DemoBadge show={m.is_demo} />
                    </td>
                    <td>
                      <StatusBadge status={m.status} />
                      {m.sets_p1 != null && <span className="num ml-1 text-[11px] text-sub">{m.sets_p1}-{m.sets_p2}</span>}
                    </td>
                    <td className="r">{m.prediction ? <ProbCI p={m.prediction.p1_win} ci={m.prediction.p1_ci} /> : <span className="text-dim">—</span>}</td>
                    <td className="r num">{m.prediction ? pct(1 - m.prediction.p1_win) : "—"}</td>
                    <td>
                      <Price q={m.hardrock?.p1} />
                    </td>
                    <td>
                      <Price q={m.hardrock?.p2} />
                    </td>
                    <td>{m.prediction?.data_quality || m.data_quality || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Card>
    </div>
  );
}

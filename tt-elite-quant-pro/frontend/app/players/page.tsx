"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, DemoBadge, Empty, ErrorBox, Loading, PageHeader, TableWrap, Tabs, Time } from "@/components/ui";
import { useApp } from "@/lib/app-context";
import { num, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";

interface PlayerRow {
  id: number;
  name: string;
  rating: number | null;
  uncertainty: number | null;
  matches: number;
  win_rate: number | null;
  rated_at: string | null;
  is_demo: boolean;
}

type Model = "elo" | "glicko2" | "bayes";

export default function PlayersPage() {
  const { demo } = useApp();
  const [model, setModel] = useState<Model>("glicko2");
  const [qIn, setQIn] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setQ(qIn.trim()), 300);
    return () => clearTimeout(t);
  }, [qIn]);
  const { data, error, loading, reload } = useApi<PlayerRow[]>("/api/players", { demo, model, q, limit: 500 });

  return (
    <div>
      <PageHeader title="PLAYER RATINGS" subtitle="Latest rating per player from the selected rating engine." />
      <Card
        title="Ratings"
        right={
          <>
            <input className="inp w-44" placeholder="Search player…" value={qIn} onChange={(e) => setQIn(e.target.value)} aria-label="Search player" />
            <Tabs<Model>
              value={model}
              onChange={setModel}
              options={[
                { value: "elo", label: "Elo" },
                { value: "glicko2", label: "Glicko-2" },
                { value: "bayes", label: "Bayes" },
              ]}
            />
          </>
        }
      >
        <ErrorBox error={error} onRetry={reload} />
        {loading && !data && <Loading />}
        {data && data.length === 0 && <Empty>No players{demo ? "" : " in LIVE data"}.</Empty>}
        {data && data.length > 0 && (
          <TableWrap maxH="72vh">
            <table className="tbl">
              <thead>
                <tr>
                  <th className="r">#</th>
                  <th>Player</th>
                  <th className="r">Rating</th>
                  <th className="r">Uncertainty</th>
                  <th className="r">Matches</th>
                  <th className="r">Win rate</th>
                  <th>Rated at</th>
                </tr>
              </thead>
              <tbody>
                {data.map((p, i) => (
                  <tr key={p.id}>
                    <td className="r text-dim">{i + 1}</td>
                    <td>
                      <Link href={`/players/${p.id}`} className="font-medium hover:text-accent">
                        {p.name}
                      </Link>{" "}
                      <DemoBadge show={p.is_demo} />
                    </td>
                    <td className="r">{num(p.rating, 0)}</td>
                    <td className="r text-sub">{p.uncertainty != null ? `±${num(p.uncertainty, 0)}` : "—"}</td>
                    <td className="r">{p.matches}</td>
                    <td className="r">{pct(p.win_rate)}</td>
                    <td>
                      <Time iso={p.rated_at} />
                    </td>
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

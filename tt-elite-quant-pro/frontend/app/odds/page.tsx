"use client";

import Link from "next/link";
import { CsvUpload, ManualOddsEntry } from "@/components/odds-entry";
import { ScreenshotImport } from "@/components/screenshot-import";
import { Card, DemoBadge, DraftKingsNote, Empty, ErrorBox, FreshnessBadge, Loading, PageHeader, TableWrap, Time } from "@/components/ui";
import { useApp } from "@/lib/app-context";
import { american } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { MatchWithPred } from "@/lib/types";

export default function OddsIndexPage() {
  const { demo } = useApp();
  const { data, error, loading, reload } = useApi<MatchWithPred[]>("/api/matches", { demo, status: "SCHEDULED", days_back: 0, days_ahead: 3, limit: 300 });

  return (
    <div className="space-y-3">
      <PageHeader
        title="ODDS COMPARISON"
        subtitle={
          <span className="inline-flex flex-wrap items-center gap-1.5">
            Hard Rock Bet (executable) vs DraftKings <DraftKingsNote />
          </span>
        }
      />
      <div className="grid gap-3 xl:grid-cols-3">
        <Card title="Choose an upcoming match" className="xl:col-span-2">
          <ErrorBox error={error} onRetry={reload} />
          {loading && !data && <Loading />}
          {data && data.length === 0 && <Empty>No upcoming matches{demo ? "" : " in LIVE data"}.</Empty>}
          {data && data.length > 0 && (
            <TableWrap maxH="70vh">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Match</th>
                    <th className="r">Hard Rock P1</th>
                    <th className="r">Hard Rock P2</th>
                    <th>Quote</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.map((m) => (
                    <tr key={m.id}>
                      <td>
                        <Time iso={m.scheduled_at} />
                      </td>
                      <td>
                        {m.player1.name} vs {m.player2.name} <DemoBadge show={m.is_demo} />
                      </td>
                      <td className="r num">{american(m.hardrock?.p1?.american)}</td>
                      <td className="r num">{american(m.hardrock?.p2?.american)}</td>
                      <td>
                        <FreshnessBadge status={m.hardrock?.p1?.freshness || "UNAVAILABLE"} />
                      </td>
                      <td>
                        <Link className="text-accent hover:underline" href={`/odds/${m.id}`} data-testid="odds-link">
                          Compare →
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          )}
        </Card>
        <div className="space-y-3">
          <ScreenshotImport onStored={reload} />
          <ManualOddsEntry onStored={reload} />
          <CsvUpload
            title="Odds CSV import"
            path="/api/odds/import-csv"
            help="Columns: match_source_ref, bookmaker, market, selection, line, american, quoted_at_utc, is_closing. Rows are matched to LIVE (non-demo) matches by source ref; unmatched rows are rejected."
          />
        </div>
      </div>
    </div>
  );
}

"use client";

import { useRef, useState } from "react";
import { BetModal, type BetPrefill } from "@/components/bet-modal";
import { OpportunityCard, recToPrefill } from "@/components/opportunity-card";
import { Card, ErrorBox, Loading, PageHeader, Tabs } from "@/components/ui";
import { useApp } from "@/lib/app-context";
import { keyLabel } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Recommendation } from "@/lib/types";

interface OppResp {
  items: Recommendation[];
  qualifying: number;
  message: string | null;
  filters: Record<string, unknown>;
}

type F = "ALL" | "QUALIFIES" | "WATCH" | "PASS";
const PAGE = 30;

export default function OpportunitiesPage() {
  const { demo } = useApp();
  const [filter, setFilter] = useState<F>("ALL");
  const [shown, setShown] = useState(PAGE);
  const [prefill, setPrefill] = useState<BetPrefill | null>(null);
  const recorded = useRef(false);
  const { data, error, loading, reload } = useApi<OppResp>("/api/opportunities", { demo, status: filter === "ALL" ? undefined : filter, limit: 200 });

  const showNoQualifying = data && data.qualifying === 0 && (filter === "ALL" || filter === "QUALIFIES");

  return (
    <div>
      <PageHeader
        title="BET OPPORTUNITIES"
        subtitle="Hard Rock Bet prices scanned against model estimates. Estimated EV is conditional on the model being accurate."
        right={
          <>
            <Tabs<F>
              value={filter}
              onChange={(v) => {
                setFilter(v);
                setShown(PAGE);
              }}
              options={[
                { value: "ALL", label: "All" },
                { value: "QUALIFIES", label: "Qualifies" },
                { value: "WATCH", label: "Watch" },
                { value: "PASS", label: "Pass" },
              ]}
            />
            <button className="btn btn-ghost" onClick={reload}>
              Refresh
            </button>
          </>
        }
      />
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data && <Loading />}
      {data && (
        <div className="space-y-3">
          {showNoQualifying && (
            <div data-testid="no-qualifying" className="rounded-lg border border-line2 bg-panel px-4 py-8 text-center">
              <div className="text-xl font-bold tracking-[0.12em] text-ink">NO QUALIFYING BETS FOUND.</div>
              <p className="mt-1 text-xs text-sub">No current Hard Rock price passes every filter. Passing is a valid outcome.</p>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3 text-xs text-sub">
            <span className="num">
              {data.items.length} shown · <b className="text-ink">{data.qualifying}</b> qualifying
            </span>
            <details className="cursor-pointer">
              <summary>Active filters</summary>
              <div className="mt-1 flex flex-wrap gap-1">
                {Object.entries(data.filters || {}).map(([k, v]) => (
                  <span key={k} className="num rounded bg-panel2 px-1.5 py-0.5 text-[10px]">
                    {keyLabel(k)}: {String(v)}
                  </span>
                ))}
              </div>
            </details>
          </div>
          {data.items.length === 0 && !showNoQualifying && <Card><div className="py-4 text-center text-xs text-sub">No {filter.toLowerCase()} items.</div></Card>}
          <div className="grid gap-3 2xl:grid-cols-2">
            {data.items.slice(0, shown).map((r) => (
              <OpportunityCard key={r.id} r={r} onBet={(x) => setPrefill(recToPrefill(x))} />
            ))}
          </div>
          {data.items.length > shown && (
            <div className="text-center">
              <button className="btn" onClick={() => setShown((s) => s + PAGE)}>
                Show more ({data.items.length - shown} remaining)
              </button>
            </div>
          )}
        </div>
      )}
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

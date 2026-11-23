"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { american, dec, isNum, keyLabel, marketLabel, pct } from "@/lib/format";
import type { Recommendation } from "@/lib/types";
import { Badge, DemoBadge, EvValue, FreshnessBadge, KV, StatusBadge, Time, cx } from "./ui";

export function OpportunityCard({ r, onBet, onChanged }: { r: Recommendation; onBet: (r: Recommendation) => void; onChanged?: () => void }) {
  const [skipping, setSkipping] = useState(false);
  const [action, setAction] = useState(r.user_action);
  const [err, setErr] = useState<string | null>(null);
  const m = r.match;
  const comps = r.model_agreement?.components || {};
  const [lo, hi] = r.prob_interval || [null, null];

  const skip = async () => {
    setSkipping(true);
    setErr(null);
    try {
      const res = await api<{ user_action: string }>(`/api/opportunities/${r.id}/skip`, { method: "POST" });
      setAction(res.user_action);
      onChanged?.();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSkipping(false);
    }
  };

  return (
    <article data-testid="opportunity-card" data-status={r.status} className={cx("rounded-lg border bg-panel", r.status === "QUALIFIES" ? "border-sky-500/40" : "border-line")}>
      <header className="flex flex-wrap items-start justify-between gap-2 border-b border-line px-3 py-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <h3 className="text-sm font-bold uppercase tracking-wide">
              {m.player1.name} <span className="text-dim">vs</span> {m.player2.name}
            </h3>
            <DemoBadge show={r.is_demo || m.is_demo} />
          </div>
          <div className="mt-0.5 text-[11px] text-sub">
            Competition {m.competition || "TT Elite Series"} · <Time iso={m.scheduled_at} />
            {m.tournament ? ` · ${m.tournament}` : ""}
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {action !== "RECOMMENDED" && <Badge tone="gray">{action}</Badge>}
          <StatusBadge status={r.status} />
        </div>
      </header>

      <div className="grid gap-x-6 gap-y-1 px-3 py-2 text-xs md:grid-cols-2">
        <div>
          <KV
            k="Recommended selection"
            v={
              <span className="font-semibold">
                {r.selection_name} <span className="font-normal text-sub">· {marketLabel(r.market)}{r.line != null ? ` ${r.line}` : ""}</span>
              </span>
            }
          />
          <KV k="Sportsbook" v="Hard Rock Bet" />
          <KV
            k="Available odds"
            v={
              <span className="inline-flex flex-wrap items-center justify-end gap-1.5">
                {isNum(r.decimal_odds) ? (
                  <span className="font-semibold">
                    {american(r.american_odds)} <span className="text-sub">({dec(r.decimal_odds)})</span>
                  </span>
                ) : (
                  <span className="text-sub">unavailable</span>
                )}
                <FreshnessBadge status={r.quote_status} />
              </span>
            }
          />
          <KV k="Quote captured" v={r.quote ? <Time iso={r.quote.captured_at} /> : "—"} />
          <KV k="Estimated win probability" v={pct(r.model_prob)} />
          <KV k="Break-even probability" v={pct(r.break_even)} />
          <KV k="Estimated EV" v={<EvValue ev={r.ev} />} />
        </div>
        <div>
          <KV k="Fair odds" v={r.fair_odds ? `${american(r.fair_odds.american)} (${dec(r.fair_odds.decimal)})` : "—"} />
          <KV k="Model uncertainty" v={isNum(lo) && isNum(hi) ? `${pct(lo)} – ${pct(hi)}` : "—"} />
          <KV k="Data quality" v={r.data_quality || "—"} />
          <KV k="Model agreement (spread)" v={isNum(r.model_agreement?.spread) ? pct(r.model_agreement!.spread) : "—"} />
          {Object.keys(comps).length > 0 && (
            <div className="flex flex-wrap justify-end gap-1 py-1">
              {Object.entries(comps).map(([k, v]) => (
                <span key={k} className="num rounded bg-panel2 px-1.5 py-0.5 text-[10px] text-sub" title={`${k} component probability for the selection`}>
                  {k} {pct(v)}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="grid gap-3 border-t border-line px-3 py-2 text-xs md:grid-cols-2">
        <div>
          <div className="lbl">Reasons supporting</div>
          <ul className="ml-4 list-disc space-y-0.5 text-sub">
            {(r.reasons_for || []).map((x, i) => (
              <li key={i}>{x}</li>
            ))}
            {!r.reasons_for?.length && <li className="list-none text-dim">None</li>}
          </ul>
        </div>
        <div>
          <div className="lbl">Reasons against</div>
          <ul className="ml-4 list-disc space-y-0.5 text-sub">
            {(r.reasons_against || []).map((x, i) => (
              <li key={i}>{x}</li>
            ))}
            {!r.reasons_against?.length && <li className="list-none text-dim">None</li>}
          </ul>
        </div>
      </div>

      {r.filters && (
        <div className="flex flex-wrap gap-1 border-t border-line px-3 py-2" aria-label="Filters">
          {Object.entries(r.filters).map(([k, ok]) => (
            <span
              key={k}
              className={cx("rounded border px-1.5 py-[1px] text-[10px] font-semibold uppercase tracking-wider", ok ? "border-sky-500/30 text-sky-300" : "border-slate-600 text-slate-500 line-through")}
              title={ok ? "filter passed" : "filter failed"}
            >
              {ok ? "✓" : "✗"} {keyLabel(k)}
            </span>
          ))}
        </div>
      )}

      <footer className="flex flex-wrap items-center gap-2 border-t border-line px-3 py-2">
        <button className="btn btn-primary" data-testid="btn-bet-placed" onClick={() => onBet(r)} disabled={action === "PLACED"}>
          BET PLACED
        </button>
        <button className="btn" data-testid="btn-skip" onClick={skip} disabled={skipping || action === "SKIPPED" || action === "PLACED"}>
          {action === "SKIPPED" ? "SKIPPED" : skipping ? "Skipping…" : "SKIP BET"}
        </button>
        <Link className="btn btn-ghost" href={`/matches/${m.id}`}>
          VIEW ANALYSIS
        </Link>
        {err && <span className="text-xs text-red-300">{err}</span>}
      </footer>
    </article>
  );
}

export function recToPrefill(r: Recommendation) {
  return {
    recommendation_id: r.id,
    match: r.match,
    market: r.market,
    selection: r.selection,
    line: r.line,
    recommended_american: r.american_odds,
    model_prob: r.model_prob,
    prob_interval: r.prob_interval,
  };
}

"use client";

import { useEffect, useMemo, useState } from "react";
import { api, ApiError, detailMessage } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { american as fmtAm, americanToDecimal, dec, isNum, localInputToIso, marketLabel, nowLocalInput, pct, usd } from "@/lib/format";
import type { MatchBrief, MatchWithPred } from "@/lib/types";
import { DemoBadge, Field, Modal, Notice, Time } from "./ui";

export const MARKETS = ["match_winner", "set_handicap", "point_handicap", "total_points", "correct_score", "set_winner"] as const;

export interface BetPrefill {
  recommendation_id?: number | null;
  match?: MatchBrief | null;
  market?: string;
  selection?: string;
  line?: number | null;
  recommended_american?: number | null;
  model_prob?: number | null;
  prob_interval?: (number | null)[] | null;
}

interface StakeSim {
  fixed_stake: number;
  fixed_pct_stake: number;
  fractional_kelly_stake: number;
  full_kelly_fraction: number;
  kelly_multiplier: number;
  kelly_sensitivity: { case: string; prob: number; full_kelly_frac: number; fractional_stake: number }[];
  note: string;
}

function uuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export function BetModal({ open, onClose, prefill, onRecorded }: { open: boolean; onClose: () => void; prefill?: BetPrefill | null; onRecorded?: (betId: number) => void }) {
  return open ? <BetForm onClose={onClose} prefill={prefill || {}} onRecorded={onRecorded} /> : null;
}

function BetForm({ onClose, prefill, onRecorded }: { onClose: () => void; prefill: BetPrefill; onRecorded?: (betId: number) => void }) {
  const { demo } = useApp();
  // generated exactly once per modal open (component mounts on open)
  const [clientRequestId] = useState(uuid);
  const [matches, setMatches] = useState<MatchWithPred[] | null>(null);
  const [match, setMatch] = useState<MatchBrief | null>(prefill.match || null);
  const [market, setMarket] = useState(prefill.market || "match_winner");
  const [selection, setSelection] = useState(prefill.selection || "p1");
  const [line, setLine] = useState(prefill.line != null ? String(prefill.line) : "");
  const [am, setAm] = useState("");
  const [stake, setStake] = useState("");
  const [placedAt, setPlacedAt] = useState(nowLocalInput);
  const [betRef, setBetRef] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dup, setDup] = useState<{ msg: string; canOverride: boolean; existing?: number } | null>(null);
  const [riskWarnings, setRiskWarnings] = useState<string[] | null>(null);
  const [allowDuplicate, setAllowDuplicate] = useState(false);
  const [done, setDone] = useState<{ id: number; warnings: string[] } | null>(null);

  // stake simulation (educational)
  const [simOpen, setSimOpen] = useState(false);
  const [simBankroll, setSimBankroll] = useState("");
  const [simProb, setSimProb] = useState(isNum(prefill.model_prob) ? (prefill.model_prob * 100).toFixed(1) : "");
  const [sim, setSim] = useState<StakeSim | null>(null);
  const [simErr, setSimErr] = useState<string | null>(null);

  const fixedMatch = !!prefill.match;

  useEffect(() => {
    if (fixedMatch) return;
    api<MatchWithPred[]>("/api/matches", { query: { demo, status: "SCHEDULED", days_back: 0, days_ahead: 3, limit: 300 } })
      .then(setMatches)
      .catch((e) => setError((e as Error).message));
  }, [demo, fixedMatch]);

  const amNum = am.trim() === "" ? NaN : Number(am);
  const decimal = isNum(amNum) ? americanToDecimal(amNum) : null;
  const stakeNum = Number(stake);
  const payout = decimal && stakeNum > 0 ? stakeNum * decimal : null;
  const profit = payout != null ? payout - stakeNum : null;

  const selOptions = useMemo(() => {
    if (!match) return [];
    return [
      { v: "p1", l: match.player1.name },
      { v: "p2", l: match.player2.name },
    ];
  }, [match]);

  const amError = am.trim() !== "" && (!isNum(amNum) || !Number.isInteger(amNum) || (amNum > -100 && amNum < 100)) ? "American odds must be ≤ -100 or ≥ +100" : null;

  const valid = !!match && !!selection && decimal != null && !amError && stakeNum > 0 && !!placedAt && (market === "match_winner" || selection.length <= 16);

  const submit = async (opts: { allow_duplicate?: boolean; override_risk?: boolean } = {}) => {
    if (!match || !valid) return;
    setBusy(true);
    setError(null);
    const allowDup = opts.allow_duplicate ?? allowDuplicate;
    try {
      const body = {
        recommendation_id: prefill.recommendation_id ?? null,
        match_id: match.id,
        market,
        selection,
        line: market !== "match_winner" && line.trim() !== "" ? Number(line) : null,
        accepted_american: Math.round(amNum),
        stake: Math.round(stakeNum * 100) / 100,
        placed_at: localInputToIso(placedAt),
        bet_ref: betRef.trim() || null,
        notes: notes.trim() || null,
        client_request_id: clientRequestId,
        allow_duplicate: allowDup,
        override_risk: !!opts.override_risk,
      };
      const res = await api<{ bet: { id: number }; warnings: string[] }>("/api/bets", { body });
      setDone({ id: res.bet.id, warnings: res.warnings || [] });
      setDup(null);
      setRiskWarnings(null);
      onRecorded?.(res.bet.id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const d = (e.detail || {}) as { needs_allow_duplicate?: boolean; existing_bet_id?: number };
        setDup({ msg: detailMessage(e.detail), canOverride: !!d.needs_allow_duplicate, existing: d.existing_bet_id });
        setRiskWarnings(null);
      } else if (e instanceof ApiError && e.status === 422 && e.detail && typeof e.detail === "object" && !Array.isArray(e.detail) && "warnings" in e.detail) {
        setRiskWarnings(((e.detail as { warnings: string[] }).warnings || []).map(String));
        setDup(null);
      } else {
        setError((e as Error).message);
      }
    } finally {
      setBusy(false);
    }
  };

  const runSim = async () => {
    setSimErr(null);
    setSim(null);
    const p = Number(simProb) / 100;
    const b = Number(simBankroll);
    if (!decimal) return setSimErr("Enter the accepted American odds first.");
    if (!(p > 0 && p < 1)) return setSimErr("Enter a win probability between 0 and 100%.");
    if (!(b > 0)) return setSimErr("Enter a positive bankroll.");
    const [lo, hi] = prefill.prob_interval || [];
    try {
      setSim(
        await api<StakeSim>("/api/bankroll/stake-sim", {
          body: { bankroll: b, prob: p, decimal_odds: decimal, prob_low: isNum(lo) && lo > 0 && lo < 1 ? lo : null, prob_high: isNum(hi) && hi > 0 && hi < 1 ? hi : null },
        }),
      );
    } catch (e) {
      setSimErr((e as Error).message);
    }
  };

  useEffect(() => {
    if (!simOpen || simBankroll) return;
    api<{ summary: { bankroll: number } }>("/api/bankroll", { query: { demo } })
      .then((r) => setSimBankroll(r.summary.bankroll > 0 ? String(r.summary.bankroll) : "1000"))
      .catch(() => setSimBankroll("1000"));
  }, [simOpen, simBankroll, demo]);

  return (
    <Modal open onClose={onClose} title="BET PLACED — record your Hard Rock Bet wager" wide testId="bet-modal">
      {done ? (
        <div className="space-y-3" data-testid="bet-recorded">
          <Notice tone="blue">
            Bet #{done.id} recorded with status PLACED in My Bets{match?.is_demo ? " (DEMO ledger)" : ""}.
          </Notice>
          {done.warnings.length > 0 && (
            <Notice tone="amber">
              Recorded with risk-limit override:
              <ul className="ml-4 list-disc">
                {done.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </Notice>
          )}
          <div className="flex justify-end">
            <button className="btn btn-primary" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      ) : (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <Notice tone="gray">
            This records a bet you already placed yourself in the Hard Rock Bet app. Sportsbook: <b className="text-ink">Hard Rock Bet</b>.
          </Notice>

          {fixedMatch && match ? (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-semibold">
                {match.player1.name} vs {match.player2.name}
              </span>
              <DemoBadge show={match.is_demo} />
              <span className="text-xs text-sub">
                <Time iso={match.scheduled_at} />
              </span>
            </div>
          ) : (
            <Field label="Match">
              <select
                className="inp w-full"
                data-testid="bet-match"
                value={match?.id ?? ""}
                onChange={(e) => setMatch(matches?.find((m) => m.id === Number(e.target.value)) || null)}
                required
              >
                <option value="">{matches ? (matches.length ? "Select an upcoming match…" : "No upcoming matches") : "Loading matches…"}</option>
                {matches?.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.is_demo ? "[DEMO] " : ""}
                    {m.player1.name} vs {m.player2.name} — {new Date(m.scheduled_at).toLocaleString()}
                  </option>
                ))}
              </select>
            </Field>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Market">
              <select className="inp w-full" value={market} onChange={(e) => setMarket(e.target.value)}>
                {MARKETS.map((m) => (
                  <option key={m} value={m}>
                    {marketLabel(m)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Player / selection">
              {market === "match_winner" || market === "set_handicap" || market === "point_handicap" || market === "set_winner" ? (
                <select className="inp w-full" data-testid="bet-selection" value={selection} onChange={(e) => setSelection(e.target.value)}>
                  {selOptions.length === 0 && <option value="p1">Player 1</option>}
                  {selOptions.length === 0 && <option value="p2">Player 2</option>}
                  {selOptions.map((o) => (
                    <option key={o.v} value={o.v}>
                      {o.l}
                    </option>
                  ))}
                </select>
              ) : (
                <input className="inp w-full" maxLength={16} value={selection} onChange={(e) => setSelection(e.target.value)} placeholder="e.g. over, 3-1" />
              )}
            </Field>
            {market !== "match_winner" && (
              <Field label="Line (optional)">
                <input className="inp w-full num" inputMode="decimal" value={line} onChange={(e) => setLine(e.target.value)} placeholder="-1.5" />
              </Field>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field
              label="Actual accepted odds (American)"
              hint={
                <>
                  Enter the odds Hard Rock actually accepted, not the recommended price.
                  {isNum(prefill.recommended_american) && <> Recommended price was {fmtAm(prefill.recommended_american)}.</>}
                </>
              }
            >
              <div className="flex items-center gap-2">
                <input
                  className="inp w-full num"
                  data-testid="bet-odds"
                  inputMode="numeric"
                  value={am}
                  onChange={(e) => setAm(e.target.value.replace(/[^\d+-]/g, ""))}
                  placeholder={isNum(prefill.recommended_american) ? fmtAm(prefill.recommended_american) : "+120 / -150"}
                  required
                />
                <span className="num shrink-0 text-xs text-sub" data-testid="bet-decimal">
                  dec {decimal ? dec(decimal, 3) : "—"}
                </span>
              </div>
              {amError && <span className="mt-1 block text-[11px] text-red-300">{amError}</span>}
            </Field>
            <Field label="Actual wager amount (USD)">
              <input className="inp w-full num" data-testid="bet-stake" inputMode="decimal" value={stake} onChange={(e) => setStake(e.target.value.replace(/[^\d.]/g, ""))} placeholder="10.00" required />
            </Field>
            <Field label="Date and time placed" hint="Your browser's local time; stored as UTC.">
              <input className="inp w-full num" type="datetime-local" value={placedAt} onChange={(e) => setPlacedAt(e.target.value)} required />
            </Field>
            <Field label="Bet slip reference (optional)">
              <input className="inp w-full" maxLength={128} value={betRef} onChange={(e) => setBetRef(e.target.value)} />
            </Field>
          </div>
          <Field label="Notes (optional)">
            <textarea className="inp w-full" rows={2} maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </Field>

          <div className="grid grid-cols-2 gap-2 rounded-md border border-line bg-panel2 p-2 text-xs sm:grid-cols-4">
            <div>
              <div className="lbl">Decimal</div>
              <div className="num">{decimal ? dec(decimal, 3) : "—"}</div>
            </div>
            <div>
              <div className="lbl">Stake</div>
              <div className="num">{stakeNum > 0 ? usd(stakeNum) : "—"}</div>
            </div>
            <div>
              <div className="lbl">Potential payout</div>
              <div className="num" data-testid="bet-payout">
                {payout != null ? usd(payout) : "—"}
              </div>
            </div>
            <div>
              <div className="lbl">Net profit if won</div>
              <div className="num">{profit != null ? usd(profit) : "—"}</div>
            </div>
          </div>

          <div>
            <button type="button" className="btn btn-ghost" onClick={() => setSimOpen((o) => !o)}>
              {simOpen ? "Hide stake simulation" : "Show stake simulation"}
            </button>
            {simOpen && (
              <div className="mt-2 space-y-2 rounded-md border border-line bg-panel2 p-3">
                <Notice tone="amber">Educational stake simulation only — not a recommendation of how much to wager.</Notice>
                <div className="grid gap-2 sm:grid-cols-3">
                  <Field label="Bankroll (USD)">
                    <input className="inp w-full num" value={simBankroll} onChange={(e) => setSimBankroll(e.target.value)} />
                  </Field>
                  <Field label="Estimated win probability %">
                    <input className="inp w-full num" value={simProb} onChange={(e) => setSimProb(e.target.value)} placeholder="55" />
                  </Field>
                  <div className="flex items-end">
                    <button type="button" className="btn w-full" onClick={runSim}>
                      Simulate
                    </button>
                  </div>
                </div>
                {simErr && <div className="text-xs text-red-300">{simErr}</div>}
                {sim && (
                  <div className="space-y-2 text-xs">
                    <div className="grid grid-cols-3 gap-2">
                      <div>
                        <div className="lbl">Fixed stake</div>
                        <div className="num">{usd(sim.fixed_stake)}</div>
                      </div>
                      <div>
                        <div className="lbl">Fixed % of bankroll</div>
                        <div className="num">{usd(sim.fixed_pct_stake)}</div>
                      </div>
                      <div>
                        <div className="lbl">Fractional Kelly (×{sim.kelly_multiplier})</div>
                        <div className="num">{usd(sim.fractional_kelly_stake)}</div>
                      </div>
                    </div>
                    {sim.kelly_sensitivity.length > 0 && (
                      <table className="tbl">
                        <thead>
                          <tr>
                            <th>Case</th>
                            <th className="r">Prob</th>
                            <th className="r">Full Kelly fraction</th>
                            <th className="r">Fractional stake</th>
                          </tr>
                        </thead>
                        <tbody>
                          {sim.kelly_sensitivity.map((s) => (
                            <tr key={s.case}>
                              <td>{s.case}</td>
                              <td className="r">{pct(s.prob)}</td>
                              <td className="r">{pct(s.full_kelly_frac, 2)}</td>
                              <td className="r">{usd(s.fractional_stake)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                    <p className="text-[11px] text-dim">{sim.note}</p>
                  </div>
                )}
              </div>
            )}
          </div>

          {dup && (
            <Notice tone="amber">
              <div data-testid="bet-duplicate">{dup.msg}</div>
              {dup.existing && <div className="mt-1">Existing bet #{dup.existing}.</div>}
              {dup.canOverride && (
                <button
                  type="button"
                  className="btn mt-2"
                  disabled={busy}
                  onClick={() => {
                    setAllowDuplicate(true);
                    submit({ allow_duplicate: true });
                  }}
                >
                  This is a separate bet
                </button>
              )}
            </Notice>
          )}
          {riskWarnings && (
            <Notice tone="amber">
              <div className="font-semibold" data-testid="bet-risk-warnings">
                Risk limits exceeded:
              </div>
              <ul className="ml-4 list-disc">
                {riskWarnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
              <div className="mt-2 flex gap-2">
                <button type="button" className="btn btn-danger" disabled={busy} onClick={() => submit({ override_risk: true })}>
                  Record anyway
                </button>
                <button type="button" className="btn btn-ghost" onClick={() => setRiskWarnings(null)}>
                  Edit
                </button>
              </div>
            </Notice>
          )}
          {error && <Notice tone="red">{error}</Notice>}

          <div className="flex justify-end gap-2 border-t border-line pt-3">
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" data-testid="bet-submit" disabled={!valid || busy}>
              {busy ? "Recording…" : "Confirm bet placed"}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}

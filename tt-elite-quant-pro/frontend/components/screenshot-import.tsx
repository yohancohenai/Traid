"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { Card, Notice, TableWrap, Time } from "./ui";

interface Alt {
  match_id: number;
  label: string;
  scheduled_at: string;
  score: number;
}
interface Proposal {
  read: { p1: string; p1_american: number | null; p2: string; p2_american: number | null };
  match_id: number | null;
  match: { player1: string; player2: string; scheduled_at: string } | null;
  p1_american: number | null;
  p2_american: number | null;
  ocr_confidence: number;
  needs_review: boolean;
  reasons: string[];
  alternatives: Alt[];
}
interface Resp {
  read_at: string;
  proposals: Proposal[];
  ocr_text: string;
  note: string;
}
interface RowState {
  use: boolean;
  matchId: number | "";
  a1: string;
  a2: string;
  p: Proposal;
}

const validAm = (s: string) => {
  const n = Number(s);
  return s.trim() !== "" && Number.isInteger(n) && (n <= -100 || n >= 100);
};

/** HARD ROCK SCREENSHOT IMPORT: free local OCR -> proposals -> you confirm -> POST /api/odds/manual. Nothing is saved
 * until you press "Save confirmed prices". */
export function ScreenshotImport({ onStored }: { onStored?: () => void }) {
  const { demo, tz } = useApp();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [rows, setRows] = useState<RowState[] | null>(null);
  const [readAt, setReadAt] = useState<string | null>(null);
  const [ocrText, setOcrText] = useState("");
  const [saved, setSaved] = useState<string | null>(null);

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setErr(null);
    setSaved(null);
    setRows(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api<Resp>("/api/odds/screenshot", { method: "POST", form: fd, query: { demo } });
      setReadAt(r.read_at);
      setOcrText(r.ocr_text);
      setRows(
        r.proposals.map((p) => ({
          p,
          use: !p.needs_review && p.match_id !== null,
          matchId: p.match_id ?? "",
          a1: p.p1_american?.toString() ?? "",
          a2: p.p2_american?.toString() ?? "",
        })),
      );
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const set = (i: number, patch: Partial<RowState>) => setRows((rs) => rs && rs.map((r, k) => (k === i ? { ...r, ...patch } : r)));
  const chosen = (rows || []).filter((r) => r.use);
  const invalid = chosen.some((r) => r.matchId === "" || !validAm(r.a1) || !validAm(r.a2));

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      const body = chosen.flatMap((r) => [
        { match_id: r.matchId, selection: "p1", american: Number(r.a1) },
        { match_id: r.matchId, selection: "p2", american: Number(r.a2) },
      ]);
      const res = await api<{ stored: unknown[]; warnings: string[] }>("/api/odds/manual", { method: "POST", body });
      setSaved(`Saved ${res.stored.length / 2} match prices.${res.warnings.length ? " Warnings: " + res.warnings.join("; ") : ""} Re-scanning…`);
      setRows(null);
      onStored?.();
      api("/api/jobs/predict_scan", { method: "POST" })
        .then(() => setSaved((s) => (s || "").replace("Re-scanning…", "Opportunities updated.")))
        .catch(() => undefined);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Hard Rock screenshot import" testId="hr-screenshot">
      <div className="space-y-2 text-xs">
        <p className="text-[11px] text-dim">
          Screenshot the TT Elite list in the Hard Rock app and upload it right before you decide. Prices are read with free
          local OCR and matched to the official schedule. <b>Nothing is saved until you check each row and press Save.</b>{" "}
          Saved prices count as verified for 10 minutes.
        </p>
        <input
          type="file"
          accept="image/*"
          data-testid="hr-screenshot-file"
          className="block w-full text-xs text-sub file:mr-2 file:rounded file:border file:border-line2 file:bg-panel2 file:px-2 file:py-1 file:text-ink"
          onChange={(e) => upload(e.target.files?.[0])}
          disabled={busy}
        />
        {busy && <Notice tone="blue">Reading…</Notice>}
        {err && <Notice tone="red">{err}</Notice>}
        {saved && <Notice tone="blue">{saved}</Notice>}
        {rows && rows.length === 0 && (
          <Notice tone="amber">No player/price rows were found. Try a sharper screenshot of the list (moneyline column visible).</Notice>
        )}
        {rows && rows.length > 0 && (
          <>
            <div className="text-[11px] text-dim">
              Read at <Time iso={readAt} />. Amber rows need your attention. Compare every price with the Hard Rock app.
            </div>
            <TableWrap>
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-dim">
                    <th className="px-2 py-1">Use</th>
                    <th className="px-2 py-1">Read from screenshot</th>
                    <th className="px-2 py-1">Official match</th>
                    <th className="px-2 py-1">P1 odds</th>
                    <th className="px-2 py-1">P2 odds</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={i} data-testid="hr-proposal" className={r.p.needs_review ? "bg-amber-500/5" : ""}>
                      <td className="px-2 py-1 align-top">
                        <input type="checkbox" checked={r.use} onChange={(e) => set(i, { use: e.target.checked })} aria-label="use row" />
                      </td>
                      <td className="px-2 py-1 align-top">
                        <div>
                          {r.p.read.p1} <span className="tabular-nums text-dim">{r.p.read.p1_american ?? "?"}</span>
                        </div>
                        <div>
                          {r.p.read.p2} <span className="tabular-nums text-dim">{r.p.read.p2_american ?? "?"}</span>
                        </div>
                        {r.p.reasons.length > 0 && <div className="mt-1 text-[10px] text-amber-300">{r.p.reasons.join(" · ")}</div>}
                      </td>
                      <td className="px-2 py-1 align-top">
                        <select
                          className="inp w-full"
                          value={r.matchId}
                          onChange={(e) => set(i, { matchId: e.target.value ? Number(e.target.value) : "" })}
                        >
                          <option value="">— choose —</option>
                          {r.p.alternatives.map((a) => (
                            <option key={a.match_id} value={a.match_id}>
                              {a.label} ({new Date(a.scheduled_at).toLocaleTimeString([], { timeZone: tz, hour: "numeric", minute: "2-digit", hour12: true })})
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-2 py-1 align-top">
                        <input className="inp w-20 num" value={r.a1} onChange={(e) => set(i, { a1: e.target.value })} aria-label="p1 odds" />
                      </td>
                      <td className="px-2 py-1 align-top">
                        <input className="inp w-20 num" value={r.a2} onChange={(e) => set(i, { a2: e.target.value })} aria-label="p2 odds" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
            <div className="flex items-center gap-2">
              <button className="btn btn-primary" onClick={save} disabled={busy || chosen.length === 0 || invalid} data-testid="hr-save">
                Save confirmed prices ({chosen.length})
              </button>
              {invalid && <span className="text-[11px] text-amber-300">Each checked row needs a match and valid American odds.</span>}
            </div>
            <details className="text-[11px] text-dim">
              <summary>Raw OCR text</summary>
              <pre className="whitespace-pre-wrap">{ocrText}</pre>
            </details>
          </>
        )}
      </div>
    </Card>
  );
}

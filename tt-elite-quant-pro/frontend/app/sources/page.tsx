"use client";

import { useState } from "react";
import { CsvUpload } from "@/components/odds-entry";
import { Badge, Card, Empty, ErrorBox, Loading, Notice, PageHeader, StatusBadge, TableWrap, Time, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { agoFromIso } from "@/lib/format";
import { useApi } from "@/lib/hooks";

interface CatalogueItem {
  key: string;
  name: string;
  kind: string;
  is_demo: boolean;
  verification: string;
  hard_rock: boolean | string | null;
  draftkings: boolean | string | null;
  runtime: { status: string; enabled: boolean; last_success_at: string | null; last_error_at: string | null; last_error: string | null; notes: string | null } | null;
}
interface JobRun {
  job: string;
  started_at: string;
  finished_at: string | null;
  ok: boolean | null;
  detail: unknown;
}
interface Review {
  id: number;
  raw_name: string;
  normalized: string;
  source_key: string;
  source_player_ref: string | null;
  candidates: { player_id: number; name: string; score: number }[];
  status: string;
  created_at: string;
}

const JOBS = ["ingest_results", "ingest_odds", "predict_scan", "settle", "monitor", "retrain"];

function cap(v: boolean | string | null) {
  if (v === true) return "yes";
  if (v === false) return "no";
  if (v == null) return "unknown";
  return v;
}

export default function SourcesPage() {
  const src = useApi<{ catalogue: CatalogueItem[]; jobs: JobRun[] }>("/api/sources");
  const reviews = useApi<Review[]>("/api/identity/reviews", { status: "OPEN" });
  const [running, setRunning] = useState<string | null>(null);
  const [jobMsg, setJobMsg] = useState<{ tone: "red" | "blue"; text: string } | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  const runJob = async (name: string) => {
    setRunning(name);
    setJobMsg(null);
    try {
      const r = await api<unknown>(`/api/jobs/${name}`, { method: "POST" });
      setJobMsg({ tone: "blue", text: `${name}: ${JSON.stringify(r).slice(0, 400)}` });
      src.reload();
    } catch (e) {
      setJobMsg({ tone: "red", text: `${name}: ${(e as Error).message}` });
    } finally {
      setRunning(null);
    }
  };

  return (
    <div className="space-y-3">
      <PageHeader title="DATA SOURCES" subtitle="Provenance and verification status of every feed. UNVERIFIED sources are never treated as confirmed." />
      <Card title="Source catalogue">
        <ErrorBox error={src.error} onRetry={src.reload} />
        {src.loading && !src.data && <Loading />}
        {src.data && (
          <TableWrap>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Kind</th>
                  <th>Verification</th>
                  <th>Hard Rock</th>
                  <th>DraftKings</th>
                  <th>Runtime status</th>
                  <th>Last success</th>
                  <th>Last error</th>
                </tr>
              </thead>
              <tbody>
                {src.data.catalogue.map((c) => {
                  const unverified = /UNVERIFIED|NOT FOUND/i.test(c.verification);
                  return (
                    <tr key={c.key}>
                      <td>
                        <div className="font-medium">{c.name}</div>
                        <div className="text-[10px] text-dim">
                          {c.key} {c.is_demo && <Badge tone="amber">DEMO</Badge>}
                        </div>
                      </td>
                      <td>{c.kind}</td>
                      <td className="min-w-[280px] whitespace-normal">
                        <span className={cx("text-[12px] font-medium", unverified ? "text-amber-300" : "text-ink")}>{c.verification}</span>
                      </td>
                      <td className={cx(String(c.hard_rock).match(/unverified|claimed/) && "text-amber-300")}>{cap(c.hard_rock)}</td>
                      <td className={cx(String(c.draftkings).match(/unverified|claimed/) && "text-amber-300")}>
                        {cap(c.draftkings)}
                        {c.draftkings && c.draftkings !== "no" ? <div className="text-[10px] text-dim">reference only</div> : null}
                      </td>
                      <td>{c.runtime ? <StatusBadge status={c.runtime.status} /> : <span className="text-dim">not configured</span>}</td>
                      <td>
                        {c.runtime?.last_success_at ? (
                          <>
                            <Time iso={c.runtime.last_success_at} /> <span className="text-[10px] text-dim">{agoFromIso(c.runtime.last_success_at)}</span>
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="max-w-[240px] truncate text-sub" title={c.runtime?.last_error || ""}>
                        {c.runtime?.last_error ? (
                          <>
                            <Time iso={c.runtime.last_error_at} /> {c.runtime.last_error}
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Card>

      <div className="grid gap-3 xl:grid-cols-3">
        <Card title="Jobs" className="xl:col-span-2">
          <div className="mb-3 flex flex-wrap gap-2">
            {JOBS.map((j) => (
              <button key={j} className="btn" onClick={() => runJob(j)} disabled={!!running}>
                {running === j ? `Running ${j}…` : `Run ${j}`}
              </button>
            ))}
          </div>
          {jobMsg && <div className="mb-2 break-all"><Notice tone={jobMsg.tone}>{jobMsg.text}</Notice></div>}
          {src.data && src.data.jobs.length === 0 && <Empty>No job runs yet.</Empty>}
          {src.data && src.data.jobs.length > 0 && (
            <TableWrap maxH="360px">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Job</th>
                    <th>Started</th>
                    <th>Finished</th>
                    <th>Result</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {src.data.jobs.map((j, i) => (
                    <tr key={i} className="cursor-pointer align-top" onClick={() => setExpanded(expanded === i ? null : i)}>
                      <td className="font-medium">{j.job}</td>
                      <td>
                        <Time iso={j.started_at} />
                      </td>
                      <td>
                        <Time iso={j.finished_at} />
                      </td>
                      <td>{j.ok == null ? <Badge>running</Badge> : j.ok ? <Badge tone="blue">OK</Badge> : <Badge tone="red">FAILED</Badge>}</td>
                      <td className={cx("text-[11px] text-sub", expanded === i ? "whitespace-pre-wrap break-all" : "max-w-[320px] truncate")}>
                        {expanded === i ? JSON.stringify(j.detail, null, 2) : JSON.stringify(j.detail)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          )}
        </Card>
        <CsvUpload
          title="Results CSV import"
          path="/api/import/results-csv"
          help="Columns: source_ref, player1, player2, scheduled_at_utc, status, sets_p1, sets_p2, set_scores (e.g. 11-7;9-11), finished_at_utc, tournament_ref, tournament_name, tournament_level. CSV results are UNVERIFIED unless confirmed by a second source."
        />
      </div>

      <Card title={`Identity review queue (${reviews.data?.length ?? 0} open)`}>
        <ErrorBox error={reviews.error} onRetry={reviews.reload} />
        {reviews.data && reviews.data.length === 0 && <Empty>No ambiguous player names waiting for review.</Empty>}
        <div className="space-y-2">
          {reviews.data?.map((r) => (
            <ReviewItem key={r.id} r={r} onDone={reviews.reload} />
          ))}
        </div>
      </Card>
    </div>
  );
}

function ReviewItem({ r, onDone }: { r: Review; onDone: () => void }) {
  const [cand, setCand] = useState<number | "">(r.candidates?.[0]?.player_id ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const act = async (action: "MERGE" | "NEW_PLAYER" | "REJECT") => {
    setBusy(true);
    setErr(null);
    try {
      await api(`/api/identity/reviews/${r.id}/resolve`, { body: { action, player_id: action === "MERGE" ? cand || null : null } });
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="rounded-md border border-line p-2 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <span className="font-semibold">{r.raw_name}</span> <span className="text-dim">({r.normalized})</span> · source {r.source_key}
          {r.source_player_ref ? ` · ref ${r.source_player_ref}` : ""} · <Time iso={r.created_at} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select className="inp" value={cand} onChange={(e) => setCand(e.target.value ? Number(e.target.value) : "")} aria-label="Merge candidate">
            <option value="">Choose candidate…</option>
            {(r.candidates || []).map((c) => (
              <option key={c.player_id} value={c.player_id}>
                {c.name} (#{c.player_id}, score {c.score.toFixed(2)})
              </option>
            ))}
          </select>
          <button className="btn" disabled={busy || !cand} onClick={() => act("MERGE")}>
            MERGE
          </button>
          <button className="btn" disabled={busy} onClick={() => act("NEW_PLAYER")}>
            NEW_PLAYER
          </button>
          <button className="btn btn-danger" disabled={busy} onClick={() => act("REJECT")}>
            REJECT
          </button>
        </div>
      </div>
      {err && <div className="mt-1 text-red-300">{err}</div>}
    </div>
  );
}

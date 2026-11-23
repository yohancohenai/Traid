"use client";

import { useMemo, useState } from "react";
import { ReliabilityChart, TimeLineChart, withT } from "@/components/charts";
import { Badge, Card, Empty, ErrorBox, Kpi, Loading, Modal, Notice, PageHeader, StatusBadge, TableWrap, Time, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { dec, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { ReliabilityBin } from "@/lib/types";

interface Health {
  status: string;
  source?: string;
  n?: number;
  champion?: string | null;
  reference_log_loss?: number | null;
  recent_log_loss?: number | null;
  recent_brier?: number | null;
  recent_accuracy?: number | null;
  reliability?: ReliabilityBin[];
  rolling?: { n: number; at: string; log_loss: number; brier: number }[];
  scoreline_log_loss?: number | null;
  scoreline_uniform_log_loss?: number | null;
  retrain_due: boolean;
  retrain_reason: string;
}
interface Split {
  n: number;
  ece?: number;
  brier?: number;
  accuracy?: number;
  log_loss?: number;
}
interface ModelRow {
  id: number;
  name: string;
  kind: string;
  version: string;
  status: string;
  trained_at: string;
  promoted_at: string | null;
  metrics: { test?: Split; calib?: Split; vs_market_test?: { n: number; model: { brier: number; log_loss: number }; market_novig: { brier: number; log_loss: number } }; calibration_method?: string } | null;
  notes: string | null;
}

const STATUS_TONE: Record<string, string> = { CHAMPION: "blue", CANDIDATE: "amber", RETIRED: "gray", REJECTED: "red" };

export default function ModelsPage() {
  const { demo } = useApp();
  const health = useApi<Health>("/api/models/health", { demo });
  const models = useApi<ModelRow[]>("/api/models", { demo });
  const [confirm, setConfirm] = useState<ModelRow | null>(null);
  const [msg, setMsg] = useState<{ tone: "red" | "blue"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const groups = useMemo(() => {
    const g = new Map<string, ModelRow[]>();
    for (const m of models.data || []) g.set(m.version, [...(g.get(m.version) || []), m]);
    return [...g.entries()];
  }, [models.data]);

  const hasChampion = (models.data || []).some((m) => m.status === "CHAMPION");

  const promote = async () => {
    if (!confirm) return;
    setBusy(true);
    try {
      await api(`/api/models/${confirm.id}/promote`, { method: "POST" });
      setMsg({ tone: "blue", text: `${confirm.name}@${confirm.version} is now CHAMPION.` });
      setConfirm(null);
      models.reload();
      health.reload();
    } catch (e) {
      setMsg({ tone: "red", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const train = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api<{ status: string; note: string }>("/api/models/train", { method: "POST", query: { demo } });
      setMsg({ tone: "blue", text: `Training ${r.status.toLowerCase()}. ${r.note} Refresh in a few minutes.` });
    } catch (e) {
      setMsg({ tone: "red", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const h = health.data;
  const isRollback = confirm?.status === "RETIRED";

  return (
    <div className="space-y-3">
      <PageHeader
        title="MODEL PERFORMANCE"
        subtitle="Out-of-sample calibration and drift monitoring for the champion model."
        right={
          <button className="btn btn-primary" onClick={train} disabled={busy}>
            Train challenger
          </button>
        }
      />
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
      <ErrorBox error={health.error} onRetry={health.reload} />
      {health.loading && !h && <Loading />}
      {h && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
            <Kpi label="Status" value={<StatusBadge status={h.status} />} sub={h.source} />
            <Kpi label="Champion" value={<span className="text-sm">{h.champion || "—"}</span>} />
            <Kpi label="Recent log loss" value={dec(h.recent_log_loss, 4)} sub={`reference ${dec(h.reference_log_loss, 4)}`} />
            <Kpi label="Recent Brier" value={dec(h.recent_brier, 4)} />
            <Kpi label="Recent accuracy" value={pct(h.recent_accuracy)} sub={h.n ? `n=${h.n}` : undefined} />
            <Kpi label="Scoreline log loss" value={dec(h.scoreline_log_loss, 4)} sub={`uniform ${dec(h.scoreline_uniform_log_loss, 4)}`} />
          </div>
          <Notice tone={h.retrain_due ? "amber" : "gray"}>
            Retrain due: <b>{h.retrain_due ? "YES" : "no"}</b> — {h.retrain_reason}
          </Notice>
          {h.status === "NO_DATA" && <Notice tone="gray">Not enough resolved predictions in this data mode to compute health metrics.</Notice>}
          <div className="grid gap-3 lg:grid-cols-2">
            <Card title="Reliability diagram">
              <ReliabilityChart bins={h.reliability || []} />
            </Card>
            <Card title="Rolling log loss">
              <TimeLineChart
                data={withT(h.rolling || [])}
                lines={[
                  { key: "log_loss", name: "Log loss" },
                  { key: "brier", name: "Brier" },
                ]}
                height={260}
                yFmt={(v) => v.toFixed(3)}
              />
            </Card>
          </div>
        </>
      )}

      <Card title="Model versions">
        <ErrorBox error={models.error} onRetry={models.reload} />
        {models.loading && !models.data && <Loading />}
        {models.data && models.data.length === 0 && <Empty>No trained models in this data mode.</Empty>}
        {groups.length > 0 && (
          <TableWrap maxH="70vh">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Version / model</th>
                  <th>Kind</th>
                  <th>Status</th>
                  <th className="r">Calib log loss</th>
                  <th className="r">Test log loss</th>
                  <th className="r">Test Brier</th>
                  <th className="r">Test accuracy</th>
                  <th className="r">Test ECE</th>
                  <th>Calibration</th>
                  <th className="r">vs market (test LL)</th>
                  <th>Trained</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {groups.map(([ver, rows]) => (
                  <GroupRows key={ver} ver={ver} rows={rows} onPromote={setConfirm} />
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Card>

      <Modal open={!!confirm} onClose={() => setConfirm(null)} title={isRollback ? "Roll back to this model?" : "Promote this model?"}>
        {confirm && (
          <div className="space-y-3 text-xs">
            <p>
              {isRollback ? "Roll back" : "Promote"} <b>{confirm.name}@{confirm.version}</b> to CHAMPION. The current champion {hasChampion ? "will be RETIRED" : "(none)"}. New predictions will use this
              model.
            </p>
            <p className="text-sub">
              Test log loss {dec(confirm.metrics?.test?.log_loss, 4)} · market no-vig {dec(confirm.metrics?.vs_market_test?.market_novig.log_loss, 4)}
            </p>
            <div className="flex justify-end gap-2">
              <button className="btn btn-ghost" onClick={() => setConfirm(null)}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={promote} disabled={busy}>
                {isRollback ? "Roll back" : "Promote"}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

function GroupRows({ ver, rows, onPromote }: { ver: string; rows: ModelRow[]; onPromote: (m: ModelRow) => void }) {
  return (
    <>
      <tr>
        <td colSpan={12} className="bg-panel2 text-[11px] font-semibold uppercase tracking-wider text-sub">
          Version {ver}
        </td>
      </tr>
      {rows.map((m) => {
        const vm = m.metrics?.vs_market_test;
        const better = vm ? vm.model.log_loss < vm.market_novig.log_loss : null;
        return (
          <tr key={m.id}>
            <td className="pl-5 font-medium">{m.name}</td>
            <td className="text-sub">{m.kind}</td>
            <td>
              <Badge tone={STATUS_TONE[m.status] || "gray"}>{m.status}</Badge>
            </td>
            <td className="r">{dec(m.metrics?.calib?.log_loss, 4)}</td>
            <td className="r">{dec(m.metrics?.test?.log_loss, 4)}</td>
            <td className="r">{dec(m.metrics?.test?.brier, 4)}</td>
            <td className="r">{pct(m.metrics?.test?.accuracy)}</td>
            <td className="r">{dec(m.metrics?.test?.ece, 4)}</td>
            <td className="text-sub">{m.metrics?.calibration_method || "—"}</td>
            <td className={cx("r")} title={vm ? `model ${vm.model.log_loss.toFixed(4)} vs market ${vm.market_novig.log_loss.toFixed(4)} (n=${vm.n})` : ""}>
              {vm ? (
                <>
                  {dec(vm.model.log_loss, 4)} / {dec(vm.market_novig.log_loss, 4)} <span className="text-[10px] text-dim">{better ? "model better" : "market better"}</span>
                </>
              ) : (
                "—"
              )}
            </td>
            <td>
              <Time iso={m.trained_at} />
            </td>
            <td>
              {m.status !== "CHAMPION" && m.status !== "REJECTED" && (
                <button className="btn px-2 py-0.5 text-[10px]" onClick={() => onPromote(m)}>
                  {m.status === "RETIRED" ? "Roll back" : "Promote"}
                </button>
              )}
            </td>
          </tr>
        );
      })}
    </>
  );
}

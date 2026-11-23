"use client";

import { SettingsGroupForm } from "@/components/settings-form";
import { Card, Empty, ErrorBox, Loading, PageHeader, TableWrap, Time } from "@/components/ui";
import { useApi } from "@/lib/hooks";

type Val = string | number | boolean | null;
const GROUPS: { key: string; title: string; help: string; readOnly?: string[] }[] = [
  { key: "filters", title: "Filters (LIVE mode)", help: "Thresholds a Hard Rock price must pass to QUALIFY. Prefer selecting them on the calibration period (Backtesting).", readOnly: ["selected_by"] },
  { key: "filters_demo", title: "Filters (DEMO mode)", help: "Separate thresholds used only for DEMO data, so tuning on synthetic data never changes LIVE qualification.", readOnly: ["selected_by"] },
  { key: "risk", title: "Risk", help: "Stake and exposure limits checked when you record a bet; exceeding them requires an explicit override." },
  { key: "alerts", title: "Alerts", help: "Alert channels and thresholds." },
  { key: "display", title: "Display", help: "Display preferences. The header DATA MODE toggle controls LIVE/DEMO for this browser." },
  { key: "monitoring", title: "Monitoring", help: "Drift detection and retraining policy." },
];

interface AuditRow {
  id: number;
  at: string;
  actor: string;
  action: string;
  entity: string;
  entity_id: string | null;
  detail: unknown;
}

export default function SettingsPage() {
  const s = useApi<Record<string, Record<string, Val>>>("/api/settings");
  const audit = useApi<AuditRow[]>("/api/audit", { limit: 200 });

  return (
    <div className="space-y-3">
      <PageHeader title="SETTINGS" subtitle="Changes are saved per group and recorded in the audit log." />
      <ErrorBox error={s.error} onRetry={s.reload} />
      {s.loading && !s.data && <Loading />}
      {s.data &&
        GROUPS.filter((g) => s.data![g.key]).map((g) => (
          <Card key={g.key} title={g.title}>
            <p className="mb-2 text-[11px] text-dim">{g.help}</p>
            <SettingsGroupForm
              group={g.key}
              value={s.data![g.key]}
              readOnly={g.readOnly}
              onSaved={() => {
                s.reload();
                audit.reload();
              }}
            />
          </Card>
        ))}
      <Card title="Audit log (latest 200)">
        <ErrorBox error={audit.error} onRetry={audit.reload} />
        {audit.data && audit.data.length === 0 && <Empty>No audit entries.</Empty>}
        {audit.data && audit.data.length > 0 && (
          <TableWrap maxH="480px">
            <table className="tbl">
              <thead>
                <tr>
                  <th>At</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Entity</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {audit.data.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <Time iso={a.at} />
                    </td>
                    <td>{a.actor}</td>
                    <td className="font-medium">{a.action}</td>
                    <td className="text-sub">
                      {a.entity}
                      {a.entity_id ? ` #${a.entity_id}` : ""}
                    </td>
                    <td className="max-w-[420px] truncate text-[11px] text-sub" title={JSON.stringify(a.detail)}>
                      {JSON.stringify(a.detail)}
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

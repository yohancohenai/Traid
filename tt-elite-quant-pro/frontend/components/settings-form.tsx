"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Field, Notice } from "./ui";

type Val = string | number | boolean | null;

/** Generic editor for a flat settings group; PUTs only changed fields to /api/settings/{key}. */
export function SettingsGroupForm({ group, value, onSaved, readOnly = [] }: { group: string; value: Record<string, Val>; onSaved?: (v: Record<string, Val>) => void; readOnly?: string[] }) {
  const [draft, setDraft] = useState<Record<string, string | boolean>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "red" | "blue"; text: string } | null>(null);

  useEffect(() => {
    const d: Record<string, string | boolean> = {};
    for (const [k, v] of Object.entries(value)) d[k] = typeof v === "boolean" ? v : v == null ? "" : String(v);
    setDraft(d);
  }, [value]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMsg(null);
    const changes: Record<string, Val> = {};
    for (const [k, orig] of Object.entries(value)) {
      if (readOnly.includes(k)) continue;
      const d = draft[k];
      if (typeof orig === "boolean") {
        if (d !== orig) changes[k] = d as boolean;
      } else if (typeof orig === "number") {
        const n = Number(d);
        if (String(d).trim() === "" || !Number.isFinite(n)) return setMsg({ tone: "red", text: `${k} must be a number.` });
        if (n !== orig) changes[k] = n;
      } else if (d !== (orig ?? "")) changes[k] = d as string;
    }
    if (!Object.keys(changes).length) return setMsg({ tone: "red", text: "No changes." });
    setBusy(true);
    try {
      const out = await api<Record<string, Val>>(`/api/settings/${group}`, { method: "PUT", body: changes });
      setMsg({ tone: "blue", text: `Saved ${Object.keys(changes).join(", ")}.` });
      onSaved?.(out);
    } catch (e2) {
      setMsg({ tone: "red", text: (e2 as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3" data-testid={`settings-${group}`}>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {Object.entries(value).map(([k, orig]) => (
          <Field key={k} label={k.replace(/_/g, " ")}>
            {typeof orig === "boolean" ? (
              <select className="inp w-full" value={String(draft[k])} onChange={(e) => setDraft({ ...draft, [k]: e.target.value === "true" })} disabled={readOnly.includes(k)}>
                <option value="true">enabled</option>
                <option value="false">disabled</option>
              </select>
            ) : (
              <input
                className="inp w-full num"
                value={String(draft[k] ?? "")}
                onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
                disabled={readOnly.includes(k)}
                inputMode={typeof orig === "number" ? "decimal" : undefined}
              />
            )}
          </Field>
        ))}
      </div>
      <button className="btn btn-primary" type="submit" disabled={busy}>
        {busy ? "Saving…" : "Save"}
      </button>
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
    </form>
  );
}

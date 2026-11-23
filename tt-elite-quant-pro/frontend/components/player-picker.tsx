"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { PlayerRef } from "@/lib/types";

/** Searchable select over a provided player list. */
export function PlayerPicker({ players, value, onChange, label, testId }: { players: PlayerRef[]; value: PlayerRef | null; onChange: (p: PlayerRef | null) => void; label: string; testId?: string }) {
  const [q, setQ] = useState(value?.name || "");
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  const [prev, setPrev] = useState(value);
  const listId = useId();
  if (prev !== value) {
    setPrev(value);
    if (value) setQ(value.name);
  }
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  const norm = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ł/g, "l").replace(/Ł/g, "L").toLowerCase();
  const nq = norm(q.trim());
  const list = (nq && nq !== norm(value?.name || "") ? players.filter((p) => norm(p.name).includes(nq)) : players).slice(0, 60);

  return (
    <div className="relative" ref={box}>
      <span className="lbl">{label}</span>
      <input
        className="inp w-full"
        data-testid={testId}
        role="combobox"
        aria-controls={listId}
        aria-expanded={open}
        aria-label={label}
        placeholder="Search player…"
        value={q}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
          if (value) onChange(null);
        }}
      />
      {open && (
        <ul id={listId} role="listbox" className="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-line2 bg-panel shadow-xl">
          {list.length === 0 && <li className="px-2 py-1.5 text-xs text-sub">No match</li>}
          {list.map((p) => (
            <li
              key={p.id}
              role="option"
              aria-selected={value?.id === p.id}
              className="cursor-pointer px-2 py-1.5 text-xs hover:bg-sky-500/10"
              onMouseDown={(e) => {
                e.preventDefault();
                onChange(p);
                setQ(p.name);
                setOpen(false);
              }}
            >
              {p.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

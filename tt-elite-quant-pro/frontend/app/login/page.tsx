"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, setToken } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ access_token: string }>("/api/auth/login", { body: { username, password } });
      setToken(r.access_token);
      const next = new URLSearchParams(window.location.search).get("next");
      router.replace(next && next.startsWith("/") && !next.startsWith("//") && next !== "/login" ? next : "/");
    } catch (err) {
      setError((err as Error).message === "invalid credentials" ? "Invalid username or password." : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-lg border border-line bg-panel p-6 shadow-2xl" aria-label="Sign in">
        <div className="mb-5">
          <div className="text-base font-bold tracking-[0.14em]">TT ELITE</div>
          <div className="text-[11px] font-semibold tracking-[0.24em] text-accent">QUANT PRO</div>
          <p className="mt-2 text-xs text-sub">Research terminal for TT Elite Series. This software never places wagers.</p>
        </div>
        <label className="mb-3 block">
          <span className="lbl">Username</span>
          <input className="inp w-full" name="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        </label>
        <label className="mb-4 block">
          <span className="lbl">Password</span>
          <input className="inp w-full" name="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {error && (
          <div role="alert" className="mb-3 rounded border border-red-500/30 bg-red-500/5 px-2 py-1.5 text-xs text-red-300">
            {error}
          </div>
        )}
        <button type="submit" className="btn btn-primary w-full py-2" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

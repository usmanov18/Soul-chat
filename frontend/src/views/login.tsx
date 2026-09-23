"use client";

import { useState, type FormEvent } from "react";
import { ApiError, endpoints, setToken } from "@/lib/api";

export function LoginForm({ onDone }: { onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const tokens = await endpoints.login({ username, password });
      setToken(tokens.access_token);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kirishda xatolik");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen place-items-center p-6">
      <form onSubmit={submit} className="glass w-full max-w-sm space-y-4 p-7">
        <div>
          <h1 className="text-xl font-semibold">SoulChat Admin</h1>
          <p className="text-xs text-slate-400">Moderator yoki admin akkaunti bilan kiring</p>
        </div>
        <input className="input" placeholder="username" value={username} onChange={(e) => setUsername(e.target.value)} />
        <input
          className="input"
          type="password"
          placeholder="parol"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error ? <p className="text-xs text-rose-300">{error}</p> : null}
        <button className="btn w-full justify-center" disabled={busy || !username || !password}>
          {busy ? "Tekshirilmoqda…" : "Kirish"}
        </button>
      </form>
    </div>
  );
}
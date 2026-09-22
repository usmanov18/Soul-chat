"use client";

import { useEffect, useState } from "react";
import { EmptyState, Panel } from "@/components/cards";
import { endpoints } from "@/lib/api";

export function UsersView() {
  const [rows, setRows] = useState<Awaited<ReturnType<typeof endpoints.users>>>([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Record<string, unknown[]> | null>(null);

  useEffect(() => {
    void endpoints.users().then(setRows).catch(() => setRows([]));
  }, []);

  const runSearch = async () => {
    if (!query.trim()) return setResults(null);
    setResults(await endpoints.search(query.trim()));
  };

  return (
    <div className="space-y-6">
      <Panel
        title="Qidiruv"
        subtitle="Kod, username, ID, ism, sana, media bo'yicha"
        action={
          <div className="flex gap-2">
            <input className="input w-56" placeholder="A-0042 / akbar / 123456" value={query} onChange={(e) => setQuery(e.target.value)} />
            <button className="btn" onClick={() => void runSearch()}>
              Izlash
            </button>
          </div>
        }
      >
        {results ? (
          <div className="space-y-3 text-sm text-slate-300">
            {Object.entries(results).map(([section, items]) => (
              <div key={section}>
                <p className="stat-label">{section}</p>
                <pre className="mt-1 overflow-x-auto rounded-xl bg-ink-950/60 p-3 text-xs">
                  {JSON.stringify(items, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState message="Natija yo'q" />
        )}
      </Panel>

      <Panel title="Foydalanuvchilar">
        {rows.length === 0 ? (
          <EmptyState message="Foydalanuvchi yo'q" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="table-head">Ism</th>
                  <th className="table-head">Username</th>
                  <th className="table-head">Rol</th>
                  <th className="table-head">Xabar</th>
                  <th className="table-head">Suhbat</th>
                  <th className="table-head">Holat</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((user) => (
                  <tr key={user.id} className="border-t border-white/5">
                    <td className="table-cell">
                      {user.first_name} {user.last_name}
                    </td>
                    <td className="table-cell text-slate-400">@{user.username ?? "—"}</td>
                    <td className="table-cell">
                      <span className="chip">{user.role}</span>
                    </td>
                    <td className="table-cell">{user.messages_sent}</td>
                    <td className="table-cell">{user.topics_created}</td>
                    <td className="table-cell">
                      {user.is_banned ? <span className="chip border-rose-400/30 text-rose-200">banned</span> : null}
                      {user.is_muted ? <span className="chip border-amber-400/30 text-amber-200">muted</span> : null}
                      {user.warns > 0 ? <span className="chip">warn {user.warns}</span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
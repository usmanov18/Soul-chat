"use client";

import { useState, useEffect } from "react";
import { EmptyState, Panel } from "@/components/cards";
import { endpoints, type AuditRow } from "@/lib/api";

export function LogsView() {
  const [rows, setRows] = useState<AuditRow[]>([]);

  useEffect(() => {
    void endpoints.audit().then(setRows).catch(() => setRows([]));
  }, []);

  return (
    <Panel title="Audit log" subtitle="Kim, qachon, qayerdan, nima qildi">
      {rows.length === 0 ? (
        <EmptyState message="Log yo'q" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className="table-head">Vaqt</th>
                <th className="table-head">Amal</th>
                <th className="table-head">Actor</th>
                <th className="table-head">Manba</th>
                <th className="table-head">IP</th>
                <th className="table-head">Xabar</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-t border-white/5">
                  <td className="table-cell text-slate-400">{row.at?.slice(0, 19).replace("T", " ")}</td>
                  <td className="table-cell font-mono text-xs text-indigo-200">{row.action}</td>
                  <td className="table-cell">{row.actor_tg_id ?? "—"}</td>
                  <td className="table-cell">
                    <span className="chip">{row.source}</span>
                  </td>
                  <td className="table-cell text-slate-400">{row.ip ?? "—"}</td>
                  <td className="table-cell max-w-md truncate">{row.message ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
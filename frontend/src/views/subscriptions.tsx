"use client";

import { useCallback, useEffect, useState } from "react";
import { EmptyState, Panel } from "@/components/cards";
import { endpoints, type SubscriptionRow } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

export function SubscriptionsView() {
  const [rows, setRows] = useState<SubscriptionRow[]>([]);
  const [total, setTotal] = useState(0);
  const [membership, setMembership] = useState<"all" | "member" | "missing">("all");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const isMember = membership === "all" ? undefined : membership === "member";
      const body = await endpoints.subscriptions(isMember);
      setRows(body.items);
      setTotal(body.total);
    } catch {
      setRows([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [membership]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Panel
      title="Majburiy obunalar"
      subtitle={`Jami ${total} ta yozuv (TZ 5)`}
      action={
        <select
          className="input w-48"
          value={membership}
          onChange={(e) => setMembership(e.target.value as "all" | "member" | "missing")}
        >
          <option value="all">Barchasi</option>
          <option value="member">A'zolar</option>
          <option value="missing">Obuna yo'q</option>
        </select>
      }
    >
      {loading ? (
        <EmptyState message="Yuklanmoqda..." />
      ) : rows.length === 0 ? (
        <EmptyState message="Yozuv yo'q" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className="table-head">Foydalanuvchi</th>
                <th className="table-head">Turi</th>
                <th className="table-head">Chat ID</th>
                <th className="table-head">Holat</th>
                <th className="table-head">Tekshirilgan</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`${row.tg_id}-${row.kind}-${index}`} className="border-t border-white/5">
                  <td className="table-cell">
                    {row.first_name ?? "—"}{" "}
                    <span className="text-slate-400">{row.username ? `@${row.username}` : row.tg_id}</span>
                  </td>
                  <td className="table-cell">
                    <span className="chip">{row.kind}</span>
                  </td>
                  <td className="table-cell font-mono text-xs text-slate-400">{row.chat_id}</td>
                  <td className="table-cell">
                    {row.is_member ? (
                      <span className="chip border-emerald-400/30 bg-emerald-400/10 text-emerald-200">
                        a'zo
                      </span>
                    ) : (
                      <span className="chip border-rose-400/30 bg-rose-400/10 text-rose-200">
                        obuna yo'q
                      </span>
                    )}
                  </td>
                  <td className="table-cell text-slate-400">{formatDateTime(row.checked_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

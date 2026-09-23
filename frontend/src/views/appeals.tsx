"use client";

import { useCallback, useEffect, useState } from "react";
import { EmptyState, Panel } from "@/components/cards";
import { endpoints, type AppealRow } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

/**
 * D5: appeals written by banned/muted users via /appeal. Admins lift the ban
 * (through the audited unban); moderators may only reject.
 */
export function AppealsView() {
  const [rows, setRows] = useState<AppealRow[]>([]);
  const [status, setStatus] = useState("pending");
  const [notice, setNotice] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await endpoints.appeals(status));
    } catch {
      setRows([]);
    }
  }, [status]);

  useEffect(() => {
    void load();
  }, [load]);

  const decide = async (row: AppealRow, decision: "approve" | "reject") => {
    const note = window.prompt(`#${row.id} uchun izoh (ixtiyoriy):`) ?? "";
    setBusyId(row.id);
    setNotice(null);
    try {
      const result = await endpoints.decideAppeal(row.id, decision, note);
      setNotice(`Murojaat #${result.id}: ${result.status}`);
      await load();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Qaror saqlanmadi");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Panel
      title="Apellyatsiyalar"
      subtitle="Ban/mute dagi foydalanuvchilar murojaati (D5)"
      action={
        <select className="input w-44" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="pending">Kutilmoqda</option>
          <option value="approved">Tasdiqlangan</option>
          <option value="rejected">Rad etilgan</option>
          <option value="all">Barchasi</option>
        </select>
      }
    >
      {notice ? (
        <p className="mb-4 rounded-xl border border-indigo-400/30 bg-indigo-500/10 p-3 text-sm text-indigo-100">
          {notice}
        </p>
      ) : null}
      {rows.length === 0 ? (
        <EmptyState message="Murojaat yo'q" />
      ) : (
        <div className="space-y-3">
          {rows.map((row) => (
            <div key={row.id} className="glass glass-hover rounded-2xl p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono text-xs text-slate-400">#{row.id} · {row.tg_id}</span>
                <span
                  className={`chip ${
                    row.status === "approved"
                      ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-200"
                      : row.status === "rejected"
                        ? "border-rose-400/30 bg-rose-400/10 text-rose-200"
                        : "border-amber-400/30 bg-amber-400/10 text-amber-200"
                  }`}
                >
                  {row.status}
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-300">{row.text}</p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {row.status === "pending" ? (
                  <>
                    <button
                      className="btn px-2 py-1 text-xs"
                      disabled={busyId === row.id}
                      onClick={() => void decide(row, "approve")}
                    >
                      ✅ Banʼni olib tashlash
                    </button>
                    <button
                      className="btn px-2 py-1 text-xs"
                      disabled={busyId === row.id}
                      onClick={() => void decide(row, "reject")}
                    >
                      ❌ Rad etish
                    </button>
                  </>
                ) : null}
                <span className="text-xs text-slate-500">{formatDateTime(row.created_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

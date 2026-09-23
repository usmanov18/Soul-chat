"use client";

import { useCallback, useEffect, useState } from "react";
import { EmptyState, Panel } from "@/components/cards";
import { endpoints, type BackupRow } from "@/lib/api";
import { formatBytes, formatDateTime } from "@/lib/format";

export function BackupView() {
  const [rows, setRows] = useState<BackupRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [verifyStatus, setVerifyStatus] = useState<Record<number, string>>({});

  const load = useCallback(async () => {
    try {
      setRows(await endpoints.backupHistory());
    } catch {
      setRows([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const verify = async (row: BackupRow) => {
    setVerifyStatus((prev) => ({ ...prev, [row.id]: "tekshirilmoqda..." }));
    try {
      const result = await endpoints.backupVerify(row.id);
      setVerifyStatus((prev) => ({ ...prev, [row.id]: result.status }));
    } catch (error) {
      setVerifyStatus((prev) => ({
        ...prev,
        [row.id]: error instanceof Error ? error.message : "xato",
      }));
    }
  };

  const runBackup = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await endpoints.backup();
      setMessage(
        result.status === "success"
          ? `Zaxira yaratildi: ${result.path ?? ""} (${formatBytes(result.size)})`
          : `Zaxira amalga oshmadi: ${result.error ?? result.status}`
      );
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Xatolik");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel
      title="Zaxira (backup)"
      subtitle="Har kuni 02:00 da avtomatik (TZ 31)"
      action={
        <button className="btn" disabled={busy} onClick={() => void runBackup()}>
          {busy ? "Ishlanmoqda..." : "Hozir zaxiralash"}
        </button>
      }
    >
      {message ? (
        <p className="mb-4 rounded-xl border border-indigo-400/30 bg-indigo-500/10 p-3 text-sm text-indigo-100">
          {message}
        </p>
      ) : null}
      {rows.length === 0 ? (
        <EmptyState message="Zaxira tarixi bo'sh" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className="table-head">Vaqt</th>
                <th className="table-head">Manzil</th>
                <th className="table-head">Hajm</th>
                <th className="table-head">Holat</th>
                <th className="table-head">Amallar</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-t border-white/5">
                  <td className="table-cell text-slate-400">{formatDateTime(row.started_at)}</td>
                  <td className="table-cell max-w-sm truncate font-mono text-xs">{row.path ?? "—"}</td>
                  <td className="table-cell">{formatBytes(row.size)}</td>
                  <td className="table-cell">
                    {row.status === "success" ? (
                      <span className="chip border-emerald-400/30 bg-emerald-400/10 text-emerald-200">
                        success
                      </span>
                    ) : (
                      <span className="chip border-rose-400/30 bg-rose-400/10 text-rose-200">
                        {row.status}
                        {row.error ? `: ${row.error}` : ""}
                      </span>
                    )}
                  </td>
                  <td className="table-cell">
                    <div className="flex flex-wrap items-center gap-1">
                      {row.path ? (
                        <a className="btn px-2 py-1 text-xs" href={endpoints.backupFileUrl(row.id)} download>
                          ⬇️ Yuklab olish
                        </a>
                      ) : null}
                      <button className="btn px-2 py-1 text-xs" onClick={() => void verify(row)}>
                        🔍 Tekshirish
                      </button>
                      {verifyStatus[row.id] ? (
                        <span
                          className={`chip ${
                            verifyStatus[row.id] === "ok"
                              ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-200"
                              : "border-amber-400/30 bg-amber-400/10 text-amber-200"
                          }`}
                        >
                          {verifyStatus[row.id]}
                        </span>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

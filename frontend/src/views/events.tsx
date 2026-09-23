"use client";

import { useCallback, useEffect, useState } from "react";
import { EmptyState, Panel } from "@/components/cards";
import { endpoints, type EventRow } from "@/lib/api";
import { eventKindIcon, formatDateTime } from "@/lib/format";

const STATUSES = ["", "scheduled", "notified", "done", "cancelled"];

const STATUS_TONES: Record<string, string> = {
  scheduled: "border-sky-400/30 bg-sky-400/10 text-sky-200",
  notified: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  done: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
  cancelled: "border-slate-400/30 bg-slate-400/10 text-slate-200",
};

export function EventsView() {
  const [rows, setRows] = useState<EventRow[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("");
  const [topicCode, setTopicCode] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const body = await endpoints.events({
        status: status || undefined,
        topic_code: topicCode.trim() || undefined,
      });
      setRows(body.items);
      setTotal(body.total);
    } catch {
      setRows([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [status, topicCode]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Panel
      title="Eventlar"
      subtitle={`Jami ${total} ta hodisa (TZ 13)`}
      action={
        <div className="flex gap-2">
          <input
            className="input w-40"
            placeholder="A-0042"
            value={topicCode}
            onChange={(e) => setTopicCode(e.target.value)}
          />
          <select className="input w-40" value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {value === "" ? "Barcha holatlar" : value}
              </option>
            ))}
          </select>
        </div>
      }
    >
      {loading ? (
        <EmptyState message="Yuklanmoqda..." />
      ) : rows.length === 0 ? (
        <EmptyState message="Event topilmadi" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className="table-head">Turi</th>
                <th className="table-head">Nomi</th>
                <th className="table-head">Suhbat</th>
                <th className="table-head">Muddat</th>
                <th className="table-head">Joy</th>
                <th className="table-head">Holat</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((event) => (
                <tr key={event.id} className="border-t border-white/5">
                  <td className="table-cell">
                    <span aria-hidden className="mr-1">
                      {eventKindIcon(event.kind)}
                    </span>
                    {event.kind}
                  </td>
                  <td className="table-cell">
                    {event.title}
                    {event.checklist ? (
                      <span className="ml-2 text-xs text-slate-400">
                        {event.checklist.filter((c) => c.startsWith("[x]")).length}/
                        {event.checklist.length}
                      </span>
                    ) : null}
                  </td>
                  <td className="table-cell font-mono text-xs">{event.topic_code}</td>
                  <td className="table-cell text-slate-400">{formatDateTime(event.due_at)}</td>
                  <td className="table-cell text-slate-400">{event.location ?? "—"}</td>
                  <td className="table-cell">
                    <span className={`chip ${STATUS_TONES[event.status] ?? ""}`}>{event.status}</span>
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

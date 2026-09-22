"use client";

import { useCallback, useEffect, useState } from "react";
import { EmptyState, Panel, StatusChip } from "@/components/cards";
import { ApiError, endpoints, type Topic } from "@/lib/api";

export function TopicsView() {
  const [topics, setTopics] = useState<Topic[]>([]);
  const [filter, setFilter] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    const result = await endpoints.topics(filter || undefined);
    setTopics(result.items);
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (code: string, action: string) => {
    setMessage(null);
    try {
      await endpoints.topicAction(code, action, "admin panel");
      await load();
      setMessage(`${code}: ${action} bajarildi`);
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Xatolik");
    }
  };

  return (
    <Panel
      title="Suhbatlar"
      subtitle="Har bir topic faqat kod bilan yuritiladi"
      action={
        <select className="input max-w-[180px]" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">Barchasi</option>
          {["active", "frozen", "blocked", "delete_pending", "archived", "deleted"].map((status) => (
            <option key={status} value={status}>
              {status}
            </option>
          ))}
        </select>
      }
    >
      {message ? <p className="mb-3 text-xs text-slate-400">{message}</p> : null}
      {topics.length === 0 ? (
        <EmptyState message="Suhbat topilmadi" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className="table-head">Kod</th>
                <th className="table-head">Holat</th>
                <th className="table-head">Xabar</th>
                <th className="table-head">Media</th>
                <th className="table-head">Restore</th>
                <th className="table-head">Amallar</th>
              </tr>
            </thead>
            <tbody>
              {topics.map((topic) => (
                <tr key={topic.id} className="border-t border-white/5">
                  <td className="table-cell font-mono text-indigo-200">{topic.code}</td>
                  <td className="table-cell">
                    <StatusChip status={topic.status} />
                  </td>
                  <td className="table-cell">{topic.message_count}</td>
                  <td className="table-cell">{topic.media_count}</td>
                  <td className="table-cell">{topic.restore_count}</td>
                  <td className="table-cell">
                    <div className="flex gap-1.5">
                      <button
                        className="btn"
                        title="Muzlatish"
                        onClick={() => act(topic.code, "freeze")}
                      >
                        ❄️
                      </button>
                      <button
                        className="btn"
                        title="Muzlatishni bekor qilish"
                        onClick={() => act(topic.code, "unfreeze")}
                      >
                        ☀️
                      </button>
                      <button className="btn" onClick={() => act(topic.code, "restore")}>
                        ↩️
                      </button>
                      <button className="btn" onClick={() => act(topic.code, "archive")}>
                        📦
                      </button>
                      <button className="btn btn-danger" onClick={() => act(topic.code, "block")}>
                        🔒
                      </button>
                      <a className="btn" href={`/api/v1/topics/${topic.code}/archive`} download>
                        ⬇️
                      </a>
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
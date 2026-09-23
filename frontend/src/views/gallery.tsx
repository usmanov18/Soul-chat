"use client";

import { useCallback, useEffect, useState } from "react";
import { EmptyState, Panel } from "@/components/cards";
import { endpoints, type ChannelPostRow } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

const KINDS = ["", "new_topic", "gallery", "system"];

export function GalleryView() {
  const [rows, setRows] = useState<ChannelPostRow[]>([]);
  const [total, setTotal] = useState(0);
  const [kind, setKind] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const body = await endpoints.channelPosts(kind || undefined);
      setRows(body.items);
      setTotal(body.total);
    } catch {
      setRows([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [kind]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Panel
      title="Kanal galereyasi"
      subtitle={`Jami ${total} ta post (TZ 14/15)`}
      action={
        <select className="input w-40" value={kind} onChange={(e) => setKind(e.target.value)}>
          {KINDS.map((value) => (
            <option key={value} value={value}>
              {value === "" ? "Barcha turlar" : value}
            </option>
          ))}
        </select>
      }
    >
      {loading ? (
        <EmptyState message="Yuklanmoqda..." />
      ) : rows.length === 0 ? (
        <EmptyState message="Kanal posti yo'q" />
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {rows.map((post) => (
            <div key={post.id} className="glass glass-hover rounded-2xl p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="chip">{post.kind}</span>
                <span className="font-mono text-xs text-slate-400">
                  {post.topic_code ?? "—"}
                </span>
              </div>
              <pre className="mt-3 whitespace-pre-wrap break-words text-sm text-slate-300">
                {post.text ?? "(matn yo'q)"}
              </pre>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                {post.failed_reason ? (
                  <span className="chip border-rose-400/30 bg-rose-400/10 text-rose-200">
                    xato: {post.failed_reason}
                  </span>
                ) : (
                  <span className="chip border-emerald-400/30 bg-emerald-400/10 text-emerald-200">
                    chop etildi
                  </span>
                )}
                <span className="text-slate-500">{formatDateTime(post.published_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

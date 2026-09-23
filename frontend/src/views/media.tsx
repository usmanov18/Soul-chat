"use client";

import { useCallback, useEffect, useState } from "react";
import { EmptyState, Panel, StatusChip } from "@/components/cards";
import { endpoints, type MediaRow } from "@/lib/api";
import { formatBytes, formatDateTime, mediaKindIcon } from "@/lib/format";

const KINDS = ["", "photo", "video", "voice", "document", "sticker", "animation", "audio", "video_note"];

export function MediaView() {
  const [rows, setRows] = useState<MediaRow[]>([]);
  const [total, setTotal] = useState(0);
  const [kind, setKind] = useState("");
  const [topicCode, setTopicCode] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const body = await endpoints.media({
        kind: kind || undefined,
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
  }, [kind, topicCode]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Panel
      title="Media kutubxonasi"
      subtitle={`Jami ${total} ta fayl`}
      action={
        <div className="flex gap-2">
          <input
            className="input w-40"
            placeholder="A-0042"
            value={topicCode}
            onChange={(e) => setTopicCode(e.target.value)}
          />
          <select className="input w-36" value={kind} onChange={(e) => setKind(e.target.value)}>
            {KINDS.map((value) => (
              <option key={value} value={value}>
                {value === "" ? "Barcha turlar" : value}
              </option>
            ))}
          </select>
        </div>
      }
    >
      {loading ? (
        <EmptyState message="Yuklanmoqda..." />
      ) : rows.length === 0 ? (
        <EmptyState message="Media topilmadi" />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {rows.map((item) => (
            <div key={item.id} className="glass glass-hover rounded-2xl p-4">
              <div className="flex items-start justify-between gap-2">
                <span className="text-2xl" aria-hidden>
                  {mediaKindIcon(item.kind)}
                </span>
                <span className="chip">{item.topic_code}</span>
              </div>
              <p className="mt-2 line-clamp-2 min-h-10 text-sm text-slate-300">
                {item.caption ?? <span className="text-slate-500">{item.mime_type ?? item.kind}</span>}
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                <span>{formatBytes(item.file_size)}</span>
                {item.width && item.height ? (
                  <span>
                    {item.width}×{item.height}
                  </span>
                ) : null}
                {item.duration ? <span>{item.duration}s</span> : null}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {item.published_to_channel ? <span className="chip">kanalda</span> : null}
                {item.nsfw ? (
                  <span className="chip border-rose-400/30 bg-rose-400/10 text-rose-200">
                    nsfw {item.nsfw_score}
                  </span>
                ) : null}
                <span className="text-xs text-slate-500">{formatDateTime(item.created_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

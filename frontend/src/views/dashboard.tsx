"use client";

import { useState, useEffect, useCallback } from "react";
import { ActivityChart, HoursChart, MediaChart, WeeklyChart } from "@/components/charts";
import { EmptyState, Panel, StatCard } from "@/components/cards";
import { ApiError, endpoints, type Dashboard } from "@/lib/api";

function useDashboard() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await endpoints.dashboard(30));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ma'lumot olinmadi");
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 30_000);
    return () => clearInterval(timer);
  }, [load]);

  return { data, error, reload: load };
}

export function DashboardView() {
  const { data, error } = useDashboard();
  if (error) return <Panel title="Xatolik">{<EmptyState message={error} />}</Panel>;
  if (!data) return <Panel title="Yuklanmoqda">{<EmptyState message="Statistika yuklanmoqda…" />}</Panel>;

  const s = data.stats;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Foydalanuvchilar" value={s.total_users} hint={`bugun +${s.new_topics_today}`} />
        <StatCard label="Suhbatlar" value={s.total_topics} hint={`${s.active_topics} faol`} accent="from-pink-400/20" />
        <StatCard label="Xabarlar" value={s.total_messages} hint={`bugun ${s.messages_today}`} accent="from-sky-400/20" />
        <StatCard label="Media" value={s.total_media} hint={`bugun ${s.media_today}`} accent="from-emerald-400/20" />
        <StatCard label="Yopilgan" value={s.closed_topics} accent="from-amber-400/20" />
        <StatCard label="Tiklangan" value={s.restored_topics} accent="from-violet-400/20" />
        <StatCard label="O'rtacha chat" value={s.average_chat_length.toFixed(1)} hint="xabar / suhbat" />
        <StatCard
          label="D7 retention"
          value={`${(s.retention_d7 * 100).toFixed(1)}%`}
          hint={`o'rtacha ${s.average_days.toFixed(1)} kun`}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Panel title="Faollik" subtitle="Oxirgi 30 kun">
            <div className="h-72">
              <ActivityChart days={data.daily} />
            </div>
          </Panel>
        </div>
        <Panel title="Media turlari">
          <div className="h-72">
            {s.top_media.length ? <MediaChart media={s.top_media} /> : <EmptyState message="Media yo'q" />}
          </div>
        </Panel>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Eng faol soatlar" subtitle="UTC">
          <div className="h-64">
            <HoursChart hours={s.top_active_hours} />
          </div>
        </Panel>
        <Panel title="Haftalik dinamika">
          <div className="h-64">
            <WeeklyChart weekly={data.weekly} />
          </div>
        </Panel>
      </div>

      <Panel title="Top foydalanuvchilar">
        {s.top_users.length === 0 ? (
          <EmptyState message="Hozircha ma'lumot yo'q" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="table-head">Ism</th>
                  <th className="table-head">Telegram ID</th>
                  <th className="table-head">Xabarlar</th>
                  <th className="table-head">Suhbatlar</th>
                </tr>
              </thead>
              <tbody>
                {s.top_users.map((user) => (
                  <tr key={user.id} className="border-t border-white/5">
                    <td className="table-cell">{user.name}</td>
                    <td className="table-cell text-slate-400">{user.tg_id}</td>
                    <td className="table-cell">{user.messages}</td>
                    <td className="table-cell">{user.topics}</td>
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
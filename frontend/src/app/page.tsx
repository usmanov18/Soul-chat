"use client";

import { useCallback, useEffect, useState } from "react";
import { ActivityChart, HoursChart, MediaChart, WeeklyChart } from "@/components/charts";
import { EmptyState, Panel, StatCard, StatusChip } from "@/components/cards";
import { ApiError, endpoints, getToken, setToken, type AuditRow, type Dashboard, type Topic } from "@/lib/api";

type View = "dashboard" | "topics" | "users" | "logs" | "settings";

const NAV: { id: View; label: string; icon: string }[] = [
  { id: "dashboard", label: "Dashboard", icon: "📊" },
  { id: "topics", label: "Suhbatlar", icon: "💬" },
  { id: "users", label: "Foydalanuvchilar", icon: "👥" },
  { id: "logs", label: "Audit log", icon: "🧾" },
  { id: "settings", label: "Sozlamalar", icon: "⚙️" },
];

export default function Home() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [view, setView] = useState<View>("dashboard");

  useEffect(() => setAuthed(Boolean(getToken())), []);

  const logout = () => {
    setToken(null);
    setAuthed(false);
  };

  if (authed === null) {
    return <div className="grid min-h-screen place-items-center text-slate-400">Yuklanmoqda…</div>;
  }
  if (!authed) return <Login onDone={() => setAuthed(true)} />;

  return (
    <div className="mx-auto flex min-h-screen max-w-[1400px] flex-col gap-6 p-6">
      <header className="glass flex flex-wrap items-center justify-between gap-4 px-5 py-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">SoulChat AI</h1>
          <p className="text-xs text-slate-400">Telegram Private Topic Manager</p>
        </div>
        <nav className="flex flex-wrap gap-1">
          {NAV.map((item) => (
            <button
              key={item.id}
              onClick={() => setView(item.id)}
              className={`rounded-xl px-3 py-2 text-sm transition ${
                view === item.id
                  ? "border border-indigo-400/40 bg-indigo-500/15 text-white"
                  : "text-slate-300 hover:bg-white/5"
              }`}
            >
              <span className="mr-1.5">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
        <button className="btn" onClick={logout}>
          Chiqish
        </button>
      </header>

      {view === "dashboard" ? <DashboardView /> : null}
      {view === "topics" ? <TopicsView /> : null}
      {view === "users" ? <UsersView /> : null}
      {view === "logs" ? <LogsView /> : null}
      {view === "settings" ? <SettingsView /> : null}
    </div>
  );
}

/* --------------------------------------------------------------------- */
function Login({ onDone }: { onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const tokens = await endpoints.login({ username, password });
      setToken(tokens.access_token);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kirishda xatolik");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen place-items-center p-6">
      <form onSubmit={submit} className="glass w-full max-w-sm space-y-4 p-7">
        <div>
          <h1 className="text-xl font-semibold">SoulChat Admin</h1>
          <p className="text-xs text-slate-400">Moderator yoki admin akkaunti bilan kiring</p>
        </div>
        <input className="input" placeholder="username" value={username} onChange={(e) => setUsername(e.target.value)} />
        <input
          className="input"
          type="password"
          placeholder="parol"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error ? <p className="text-xs text-rose-300">{error}</p> : null}
        <button className="btn w-full justify-center" disabled={busy || !username || !password}>
          {busy ? "Tekshirilmoqda…" : "Kirish"}
        </button>
      </form>
    </div>
  );
}

/* --------------------------------------------------------------------- */
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

function DashboardView() {
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

/* --------------------------------------------------------------------- */
function TopicsView() {
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
                      <button className="btn" onClick={() => act(topic.code, "freeze")}>
                        ❄️
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

/* --------------------------------------------------------------------- */
function UsersView() {
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

/* --------------------------------------------------------------------- */
function LogsView() {
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

/* --------------------------------------------------------------------- */
function SettingsView() {
  const [items, setItems] = useState<Record<string, unknown>>({});
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await endpoints.settings();
      setItems(result.items);
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Sozlamalar olinmadi");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (key: string, value: string) => {
    setMessage(null);
    try {
      await endpoints.updateSetting(key, value);
      await load();
      setMessage(`${key} saqlandi`);
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Saqlanmadi");
    }
  };

  return (
    <Panel
      title="Sozlamalar"
      subtitle="Kod sxemasi, limitlar, moderatsiya chegaralari"
      action={
        <button
          className="btn"
          onClick={async () => {
            const result = await endpoints.backup();
            setMessage(`Backup: ${result.status} (${result.size} bayt)`);
          }}
        >
          💾 Backup
        </button>
      }
    >
      {message ? <p className="mb-3 text-xs text-slate-400">{message}</p> : null}
      {Object.keys(items).length === 0 ? (
        <EmptyState message="Sozlama yo'q" />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {Object.entries(items).map(([key, value]) => (
            <form
              key={key}
              className="flex items-center gap-2 rounded-xl border border-white/5 bg-white/[0.03] p-3"
              onSubmit={(event) => {
                event.preventDefault();
                const input = event.currentTarget.elements.namedItem("value") as HTMLInputElement;
                void save(key, input.value);
              }}
            >
              <code className="w-52 shrink-0 text-xs text-slate-400">{key}</code>
              <input className="input" name="value" defaultValue={String(value)} />
              <button className="btn">Saqlash</button>
            </form>
          ))}
        </div>
      )}
    </Panel>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import { EmptyState, Panel } from "@/components/cards";
import { ApiError, endpoints, type Enforcement, type SettingMeta } from "@/lib/api";

/** How each enforcement level is presented to the operator. */
const ENFORCEMENT_TONE: Record<Enforcement, { label: string; className: string }> = {
  enforced: { label: "Kafolatlangan", className: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200" },
  reactive: { label: "Keyin bekor qilinadi", className: "border-sky-400/30 bg-sky-400/10 text-sky-200" },
  advisory: { label: "Faqat ma'lumot", className: "border-amber-400/30 bg-amber-400/10 text-amber-200" },
};

export function EnforcementBadge({ level }: { level: Enforcement }) {
  const tone = ENFORCEMENT_TONE[level] ?? ENFORCEMENT_TONE.advisory;
  return (
    <span className={`chip shrink-0 ${tone.className}`} title={tone.label}>
      {tone.label}
    </span>
  );
}

export function SettingsView() {
  const [items, setItems] = useState<Record<string, unknown>>({});
  const [meta, setMeta] = useState<Record<string, SettingMeta>>({});
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await endpoints.settings();
      setItems(result.items);
      setMeta(result.meta ?? {});
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
          {Object.entries(items).map(([key, value]) => {
            const info = meta[key];
            return (
              <form
                key={key}
                className="flex flex-col gap-2 rounded-xl border border-white/5 bg-white/[0.03] p-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  const input = event.currentTarget.elements.namedItem("value") as HTMLInputElement;
                  void save(key, input.value);
                }}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-slate-200">
                    {info?.label ?? key}
                  </span>
                  {info ? <EnforcementBadge level={info.enforcement} /> : null}
                </div>
                {info?.note ? (
                  <p className="text-[11px] leading-relaxed text-slate-400">{info.note}</p>
                ) : null}
                <div className="flex items-center gap-2">
                  <code className="hidden shrink-0 text-[11px] text-slate-500 lg:block">{key}</code>
                  <input className="input" name="value" defaultValue={String(value)} />
                  <button className="btn">Saqlash</button>
                </div>
              </form>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
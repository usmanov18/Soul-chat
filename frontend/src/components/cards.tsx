"use client";

import type { ReactNode } from "react";

export function StatCard({
  label,
  value,
  hint,
  accent = "from-indigo-400/20",
}: {
  label: string;
  value: string | number;
  hint?: string;
  accent?: string;
}) {
  return (
    <div className="glass glass-hover relative overflow-hidden p-5">
      <div className={`pointer-events-none absolute inset-x-0 -top-24 h-40 bg-gradient-to-b ${accent} to-transparent`} />
      <p className="stat-label">{label}</p>
      <p className="stat-value mt-2">{value}</p>
      {hint ? <p className="mt-1 text-xs text-slate-400">{hint}</p> : null}
    </div>
  );
}

export function Panel({
  title,
  subtitle,
  children,
  action,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="glass p-5">
      <header className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold tracking-wide text-white">{title}</h2>
          {subtitle ? <p className="text-xs text-slate-400">{subtitle}</p> : null}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

export function StatusChip({ status }: { status: string }) {
  const tones: Record<string, string> = {
    active: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
    frozen: "border-sky-400/30 bg-sky-400/10 text-sky-200",
    blocked: "border-amber-400/30 bg-amber-400/10 text-amber-200",
    delete_pending: "border-orange-400/30 bg-orange-400/10 text-orange-200",
    archived: "border-slate-400/30 bg-slate-400/10 text-slate-200",
    deleted: "border-rose-400/30 bg-rose-400/10 text-rose-200",
  };
  return <span className={`chip ${tones[status] ?? ""}`}>{status.replace("_", " ")}</span>;
}

export function EmptyState({ message }: { message: string }) {
  return <p className="py-10 text-center text-sm text-slate-500">{message}</p>;
}

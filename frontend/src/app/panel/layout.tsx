"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { AuthGate } from "@/components/auth-gate";
import { Nav } from "@/components/nav";
import { setToken } from "@/lib/api";
import { applyTheme, currentTheme, toggleTheme } from "@/lib/theme";

export default function PanelLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  useEffect(() => {
    applyTheme(currentTheme());
  }, []);
  return (
    <AuthGate>
      <div className="mx-auto flex min-h-screen max-w-[1400px] flex-col gap-6 p-6">
        <header className="glass flex flex-wrap items-center justify-between gap-4 px-5 py-4">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">SoulChat AI</h1>
            <p className="text-xs text-slate-400">Telegram Private Topic Manager</p>
          </div>
          <Nav />
          <button
            className="btn"
            aria-label="Mavzuni almashtirish"
            onClick={() => {
              toggleTheme();
            }}
          >
            🌓
          </button>
          <button
            className="btn"
            onClick={() => {
              setToken(null);
              router.replace("/login");
            }}
          >
            Chiqish
          </button>
        </header>
        {children}
      </div>
    </AuthGate>
  );
}
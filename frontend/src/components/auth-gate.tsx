"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "@/lib/api";

/**
 * Client-side gate. The token lives in localStorage, so the check cannot run on
 * the server; every page under /panel is wrapped by this.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [state, setState] = useState<"loading" | "authed" | "anonymous">("loading");

  useEffect(() => {
    if (getToken()) setState("authed");
    else {
      setState("anonymous");
      router.replace("/login");
    }
  }, [router]);

  if (state !== "authed") {
    return <div className="grid min-h-screen place-items-center text-slate-400">Yuklanmoqda…</div>;
  }
  return <>{children}</>;
}
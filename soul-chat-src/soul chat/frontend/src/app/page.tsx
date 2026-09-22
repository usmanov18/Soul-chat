"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "@/lib/api";

/** Entry point: send the operator to the panel or the login form. */
export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace(getToken() ? "/panel" : "/login");
  }, [router]);
  return <div className="grid min-h-screen place-items-center text-slate-400">Yuklanmoqda…</div>;
}
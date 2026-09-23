"use client";

import { useRouter } from "next/navigation";
import { LoginForm } from "@/views/login";

export default function LoginPage() {
  const router = useRouter();
  return <LoginForm onDone={() => router.replace("/panel")} />;
}
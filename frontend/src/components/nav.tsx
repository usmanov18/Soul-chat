"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export type NavItem = {
  href: string;
  label: string;
  icon: string;
  /** match the path exactly instead of by prefix (the /panel index page) */
  exact?: boolean;
};

export const NAV_ITEMS: NavItem[] = [
  { href: "/panel", label: "Dashboard", icon: "📊", exact: true },
  { href: "/panel/topics", label: "Suhbatlar", icon: "💬" },
  { href: "/panel/users", label: "Foydalanuvchilar", icon: "👥" },
  { href: "/panel/media", label: "Media", icon: "🖼️" },
  { href: "/panel/events", label: "Eventlar", icon: "📅" },
  { href: "/panel/gallery", label: "Galereya", icon: "🌸" },
  { href: "/panel/subscriptions", label: "Obunalar", icon: "🔔" },
  { href: "/panel/moderation", label: "Audit log", icon: "🧾" },
  { href: "/panel/backup", label: "Zaxira", icon: "💾" },
  { href: "/panel/settings", label: "Sozlamalar", icon: "⚙️" },
];

export function Nav() {
  const pathname = usePathname();
  return (
    <nav className="flex flex-wrap gap-1">
      {NAV_ITEMS.map((item) => {
        const active = item.exact ? pathname === item.href : pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`rounded-xl px-3 py-2 text-sm transition ${
              active
                ? "border border-indigo-400/40 bg-indigo-500/15 text-white"
                : "text-slate-300 hover:bg-white/5"
            }`}
          >
            <span className="mr-1.5">{item.icon}</span>
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
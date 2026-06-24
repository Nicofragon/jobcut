"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { getHealth, type Health } from "@/lib/api";
import Logo from "./Logo";

const LINKS = [
  { href: "/", label: "Today" },
  { href: "/applications", label: "Applications" },
  { href: "/searches", label: "Searches" },
  { href: "/discovery", label: "Discovery" },
  { href: "/settings", label: "Settings" },
];

export default function Nav() {
  const pathname = usePathname();
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setOffline(true));
  }, []);

  return (
    <header className="sticky top-0 z-10 border-b border-border bg-surface/80 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-3 sm:gap-6">
        <Link href="/" className="flex shrink-0 items-center gap-2 font-semibold text-primary-strong">
          <Logo className="h-5 w-5 text-primary" /> jobcut
        </Link>
        <nav className="flex min-w-0 flex-1 gap-1 overflow-x-auto text-sm [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {LINKS.map((l) => {
            const active = l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={`shrink-0 whitespace-nowrap rounded-lg px-3 py-1.5 transition-colors ${
                  active
                    ? "bg-primary-tint font-medium text-primary-strong"
                    : "text-on-surface-variant hover:text-on-surface"
                }`}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
        <div className="hidden shrink-0 text-xs text-on-surface-faint sm:block">
          {offline ? (
            <span className="text-accent-red">API offline</span>
          ) : health ? (
            <span>
              {health.jobs} jobs · {health.applications} apps
            </span>
          ) : (
            <span>…</span>
          )}
        </div>
      </div>
    </header>
  );
}

"use client";
import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Sparkles,
  MessageSquare,
  KeyRound,
  Plug,
  BarChart3,
  FileText,
  FlaskConical,
  Activity,
  Workflow,
} from "lucide-react";
import { getStoredKey } from "@/lib/api";

const NAV_ITEMS = [
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/dashboard/keys", label: "Gateway keys", icon: KeyRound },
  { href: "/dashboard/providers", label: "Providers", icon: Plug },
];

const COMING_SOON = [
  { label: "Usage", icon: BarChart3 },
  { label: "Prompts", icon: FileText },
  { label: "Experiments", icon: FlaskConical },
  { label: "Status", icon: Activity },
  { label: "MCP", icon: Workflow },
];

export default function AppSidebar() {
  const pathname = usePathname();
  const [keySuffix, setKeySuffix] = useState<string | null>(null);

  useEffect(() => {
    const key = getStoredKey();
    setKeySuffix(key ? key.slice(-4) : null);
  }, [pathname]);

  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
      <div className="flex items-center gap-2 px-4 py-4 text-sm font-medium">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-sidebar-primary text-sidebar-primary-foreground">
          <Sparkles size={13} />
        </span>
        Gateway
      </div>

      <nav className="flex flex-1 flex-col gap-0.5 px-2">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname?.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
              }`}
            >
              <Icon size={15} />
              {label}
            </Link>
          );
        })}

        <p className="mb-1 mt-5 px-3 text-[11px] font-medium text-sidebar-foreground/40">
          Coming soon
        </p>
        {COMING_SOON.map(({ label, icon: Icon }) => (
          <div
            key={label}
            className="flex cursor-not-allowed items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-sidebar-foreground/35"
          >
            <Icon size={15} />
            {label}
          </div>
        ))}
      </nav>

      <div className="border-t border-sidebar-border px-4 py-3">
        {keySuffix ? (
          <p className="text-xs text-sidebar-foreground/60">
            Signed in <span className="font-mono">····{keySuffix}</span>
          </p>
        ) : (
          <Link href="/dashboard/keys" className="text-xs text-sidebar-foreground/60 hover:text-sidebar-foreground">
            Not signed in — get a key →
          </Link>
        )}
      </div>
    </aside>
  );
}
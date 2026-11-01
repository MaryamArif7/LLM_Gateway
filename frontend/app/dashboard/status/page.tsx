"use client";
import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { getProviderHealth, getStoredKey, type ProviderStatus, type ProviderStatusName } from "@/lib/api";

const POLL_MS = 10000;
const GRAFANA_URL = (process.env.NEXT_PUBLIC_GRAFANA_URL || "http://localhost:3001").replace(/\/$/, "");

const BADGE: Record<ProviderStatusName, { label: string; className: string }> = {
  up: { label: "Up", className: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400" },
  degraded: { label: "Degraded", className: "bg-amber-500/15 text-amber-600 dark:text-amber-400" },
  down: { label: "Down", className: "bg-red-500/15 text-red-600 dark:text-red-400" },
  recovering: { label: "Recovering", className: "bg-sky-500/15 text-sky-600 dark:text-sky-400" },
  unknown: { label: "No recent traffic", className: "bg-muted text-muted-foreground" },
};

const PROVIDER_NAMES: Record<string, string> = { openai: "OpenAI", anthropic: "Anthropic", gemini: "Google Gemini" };

function ago(iso: string | null): string {
  if (!iso) return "never";
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

export default function StatusPage() {
  const [hasKey, setHasKey] = useState<boolean | null>(null);
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setHasKey(!!getStoredKey());
  }, []);

  const load = useCallback(async () => {
    try {
      const data = await getProviderHealth();
      setProviders(data.providers);
      setCheckedAt(new Date(data.updated_at));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load provider status");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!hasKey) {
      if (hasKey === false) setLoading(false);
      return;
    }
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [hasKey, load]);

  if (hasKey === false) {
    return (
      <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-3 px-5 text-foreground">
        <h1 className="text-2xl font-semibold">Status</h1>
        <p className="text-sm text-muted-foreground">Sign in with a gateway key to see provider status.</p>
        <Link href="/dashboard/keys" className="text-sm text-primary hover:underline">
          Get a key
        </Link>
      </div>
    );
  }

  return (
    <div className="h-screen overflow-y-auto">
      <div className="mx-auto max-w-4xl px-5 py-10 text-foreground">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold">Status</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              How each provider is doing, based on real requests through this gateway.
              {checkedAt && <> Updated {checkedAt.toLocaleTimeString()}.</>}
            </p>
          </div>
          <div className="flex gap-2 text-sm">
            <a
              href={`${GRAFANA_URL}/d/gateway-traffic`}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-xl border border-border px-4 py-2 hover:bg-muted"
            >
              Traffic dashboard
            </a>
            <a
              href={`${GRAFANA_URL}/d/gateway-cost-usage`}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-xl border border-border px-4 py-2 hover:bg-muted"
            >
              Cost and usage dashboard
            </a>
          </div>
        </div>

        {error && <p className="mb-4 text-sm text-destructive">{error}</p>}
        {loading && providers.length === 0 && <p className="text-sm text-muted-foreground">Loading...</p>}

        <div className="grid gap-4 sm:grid-cols-2">
          {providers.map((p) => {
            const badge = BADGE[p.status];
            const minutes = Math.max(1, Math.round(p.window_seconds / 60));
            return (
              <section key={p.provider} className="rounded-xl border border-border bg-card p-4" aria-label={`${p.provider} status`}>
                <div className="flex items-center justify-between gap-3">
                  <h2 className="text-base font-medium">{PROVIDER_NAMES[p.provider] ?? p.provider}</h2>
                  <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${badge.className}`}>{badge.label}</span>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">{p.reason}</p>

                <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
                  <div className="rounded-lg bg-muted p-2">
                    <dd className="text-lg font-semibold tabular-nums">{p.successes}</dd>
                    <dt className="text-[11px] text-muted-foreground">answered</dt>
                  </div>
                  <div className="rounded-lg bg-muted p-2">
                    <dd className="text-lg font-semibold tabular-nums">{p.upstream_failures}</dd>
                    <dt className="text-[11px] text-muted-foreground">provider errors</dt>
                  </div>
                  <div className="rounded-lg bg-muted p-2">
                    <dd className="text-lg font-semibold tabular-nums">{p.client_failures}</dd>
                    <dt className="text-[11px] text-muted-foreground">key or request errors</dt>
                  </div>
                </dl>
                <p className="mt-1 text-[11px] text-muted-foreground">Last {minutes} minutes</p>

                <p className="mt-3 text-xs text-muted-foreground">
                  Last success {ago(p.last_success_at)} · last provider error {ago(p.last_failure_at)}
                  {p.consecutive_trips > 0 && <> · tripped {p.consecutive_trips} time{p.consecutive_trips === 1 ? "" : "s"} in a row</>}
                </p>
              </section>
            );
          })}
        </div>

        <section className="mt-8 rounded-xl border border-border bg-card p-4 text-xs text-muted-foreground">
          <h3 className="text-sm font-medium text-foreground">How to read this</h3>
          <p className="mt-2">
            With bring your own keys the gateway has no key of its own to test a provider with, so status comes from real requests.
            A provider with no recent requests shows as no recent traffic, which does not mean it is down.
          </p>
          <p className="mt-2">
            Only provider side failures count against a provider: timeouts, connection errors, 408 and 5xx. A wrong API key or a rate limit
            is shown as a key or request error and never marks a provider as down.
          </p>
          <p className="mt-2">
            When a provider keeps failing, the gateway stops calling it for a short time and sends requests to the next choice. It then lets
            one request through to check whether the provider has recovered.
          </p>
        </section>
      </div>
    </div>
  );
}

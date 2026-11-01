"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  getBudget,
  getStoredKey,
  getUsageLogs,
  getUsageSummary,
  setBudget,
  type BudgetStatus,
  type DayUsage,
  type UsageFreshness,
  type UsageLogItem,
  type UsageSummary,
} from "@/lib/api";

const RANGES = [
  { label: "Last 7 days", days: 7 },
  { label: "Last 30 days", days: 30 },
  { label: "Last 90 days", days: 90 },
];

const POLL_MS = 5000;

function formatUsd(n: number): string {
  if (n === 0) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(5)}`;
  if (n < 1) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function formatDay(date: string): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
}


function rangeStartIso(days: number): string {
  const d = new Date();
  d.setUTCHours(0, 0, 0, 0);
  d.setUTCDate(d.getUTCDate() - (days - 1));
  return d.toISOString();
}

export default function UsagePage() {
  const [hasKey, setHasKey] = useState<boolean | null>(null);
  const [days, setDays] = useState(30);
  const [feature, setFeature] = useState("");
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [budget, setBudgetState] = useState<BudgetStatus | null>(null);
  const [logs, setLogs] = useState<UsageLogItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [live, setLive] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);


  const logsRef = useRef<UsageLogItem[]>([]);
  logsRef.current = logs;

  useEffect(() => {
    setHasKey(!!getStoredKey());
  }, []);

  const loadSummary = useCallback(async () => {
    try {
      const [s, b] = await Promise.all([
        getUsageSummary({ feature: feature || undefined, from: rangeStartIso(days) }),
        getBudget(),
      ]);
      setSummary(s);
      setUpdatedAt(new Date());
      setBudgetState(b);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load usage");
    }
  }, [days, feature]);

  const loadFirstPage = useCallback(async () => {
    try {
      const page = await getUsageLogs({ limit: 25, feature: feature || undefined });
      setLogs(page.items);
      setNextCursor(page.next_cursor);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load request log");
    }
  }, [feature]);

  
  useEffect(() => {
    if (!hasKey) {
      if (hasKey === false) setLoading(false);
      return;
    }
    setLoading(true);
    Promise.all([loadSummary(), loadFirstPage()]).finally(() => setLoading(false));
  }, [hasKey, loadSummary, loadFirstPage]);

  useEffect(() => {
    if (!hasKey || !live) return;
    const timer = setInterval(async () => {
      if (document.visibilityState !== "visible") return;
      try {
        const page = await getUsageLogs({ limit: 25, feature: feature || undefined });
        const known = new Set(logsRef.current.map((r) => r.id));
        const fresh = page.items.filter((r) => !known.has(r.id));
        if (fresh.length > 0) {
          const freshIds = new Set(fresh.map((r) => r.id));
          setLogs((prev) => [...fresh, ...prev.filter((r) => !freshIds.has(r.id))]);
          loadSummary();
        }
      } catch {
    
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [hasKey, live, feature, loadSummary]);

  async function loadMore() {
    if (!nextCursor) return;
    try {
      const page = await getUsageLogs({ limit: 25, cursor: nextCursor, feature: feature || undefined });
      setLogs((prev) => [...prev, ...page.items]);
      setNextCursor(page.next_cursor);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load more");
    }
  }

  if (hasKey === false) {
    return (
      <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-3 px-5 text-foreground">
        <h1 className="text-2xl font-semibold">Usage</h1>
        <p className="text-sm text-muted-foreground">Sign in with a gateway key to see your spend.</p>
        <Link href="/dashboard/keys" className="text-sm text-primary hover:underline">
          Get a key
        </Link>
      </div>
    );
  }

  const totals = summary?.totals;

  return (
    <div className="h-screen overflow-y-auto">
      <div className="mx-auto max-w-5xl px-5 py-10 text-foreground">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold">Usage</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Spend across every provider you have connected, in one place.
            </p>
            {summary && <FreshnessLine freshness={summary.freshness} updatedAt={updatedAt} />}
          </div>
          <div className="flex gap-2">
            <select
              aria-label="Date range"
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="rounded-xl border border-border bg-card px-3 py-2 text-sm outline-none focus:border-primary/50"
            >
              {RANGES.map((r) => (
                <option key={r.days} value={r.days}>
                  {r.label}
                </option>
              ))}
            </select>
            <select
              aria-label="Feature tag"
              value={feature}
              onChange={(e) => setFeature(e.target.value)}
              className="rounded-xl border border-border bg-card px-3 py-2 text-sm outline-none focus:border-primary/50"
            >
              <option value="">All features</option>
              {(summary?.available_features ?? []).map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </div>
        </div>

        {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

        {budget && (budget.state === "warning" || budget.state === "exceeded") && (
          <div
            className={`mb-6 rounded-xl border p-4 text-sm ${
              budget.state === "exceeded"
                ? "border-destructive/50 bg-destructive/10"
                : "border-primary/40 bg-primary/5"
            }`}
          >
            {budget.state === "exceeded"
              ? `You have spent ${formatUsd(budget.month_spend)} this month, over your ${formatUsd(budget.threshold_amount ?? 0)} alert.`
              : `You have used ${budget.percent_used}% of your ${formatUsd(budget.threshold_amount ?? 0)} monthly alert (${formatUsd(budget.month_spend)} so far).`}
          </div>
        )}

        <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label="Spend" value={totals ? formatUsd(totals.cost_usd) : "..."} />
          <StatCard
            label="Requests"
            value={totals ? formatCount(totals.requests) : "..."}
            sub={totals ? `${totals.errors} failed, ${totals.fallbacks} used fallback` : undefined}
          />
          <StatCard
            label="Tokens"
            value={totals ? formatCount(totals.input_tokens + totals.output_tokens) : "..."}
            sub={totals ? `${formatCount(totals.input_tokens)} in, ${formatCount(totals.output_tokens)} out` : undefined}
          />
          <StatCard
            label="Cache hit rate"
            value={totals ? `${Math.round(totals.cache_hit_rate * 100)}%` : "..."}
            sub={totals ? `${totals.cache_hits} served from cache` : undefined}
          />
        </div>

        <section className="mb-6 rounded-xl border border-border bg-card p-4">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="text-sm font-medium">Spend per day</h2>
            <span className="text-xs text-muted-foreground">days are in UTC</span>
          </div>
          {summary ? <SpendChart days={summary.by_day} /> : <Placeholder loading={loading} />}
        </section>

        <div className="mb-6 grid gap-6 md:grid-cols-2">
          <section className="rounded-xl border border-border bg-card p-4">
            <h2 className="mb-3 text-sm font-medium">By model</h2>
            <BreakdownList
              loading={loading}
              rows={(summary?.by_model ?? []).map((m) => ({
                key: `${m.provider}/${m.model}`,
                label: m.model,
                sub: m.provider,
                cost: m.cost_usd,
                requests: m.requests,
              }))}
            />
          </section>
          <section className="rounded-xl border border-border bg-card p-4">
            <h2 className="mb-3 text-sm font-medium">By feature tag</h2>
            <BreakdownList
              loading={loading}
              rows={(summary?.by_feature ?? []).map((f) => ({
                key: f.feature,
                label: f.feature,
                cost: f.cost_usd,
                requests: f.requests,
              }))}
            />
            <p className="mt-3 text-xs text-muted-foreground">
              Send a feature_tag in your request body to label calls, for example support_bot.
            </p>
          </section>
        </div>

        <BudgetCard budget={budget} onSaved={setBudgetState} />

        <section className="rounded-xl border border-border bg-card">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <h2 className="text-sm font-medium">Request log</h2>
            <button
              onClick={() => setLive((v) => !v)}
              className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground"
            >
              <span className={`h-2 w-2 rounded-full ${live ? "bg-primary" : "bg-muted-foreground/40"}`} />
              {live ? "Live, updates every 5s" : "Paused"}
            </button>
          </div>
          <LogTable rows={logs} loading={loading} />
          {nextCursor && (
            <div className="border-t border-border p-3 text-center">
              <button onClick={loadMore} className="text-sm text-muted-foreground hover:text-foreground">
                Load older requests
              </button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
      {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

function Placeholder({ loading }: { loading: boolean }) {
  return <p className="py-6 text-center text-sm text-muted-foreground">{loading ? "Loading..." : "No data"}</p>;
}

function FreshnessLine({ freshness, updatedAt }: { freshness: UsageFreshness; updatedAt: Date | null }) {
  const latest = freshness.last_event_at ? new Date(freshness.last_event_at).toLocaleTimeString() : null;
  const lag = freshness.last_ingest_lag_seconds;
  return (
    <p className="mt-1 text-xs text-muted-foreground">
      {updatedAt && <>Updated {updatedAt.toLocaleTimeString()}. </>}
      {latest ? <>Latest request at {latest}. </> : <>No requests recorded yet. </>}
      {freshness.pipeline === "kafka" && (
        <>
          Requests are processed in batches{lag !== null ? `, the latest one was recorded ${lag.toFixed(1)}s after it happened` : ""}, so a new
          request can take a few seconds to show up.
        </>
      )}
    </p>
  );
}

function SpendChart({ days }: { days: DayUsage[] }) {
  const peak = Math.max(0, ...days.map((d) => d.cost_usd));
  if (days.every((d) => d.requests === 0)) {
    return <p className="py-10 text-center text-sm text-muted-foreground">No requests in this range yet.</p>;
  }
  return (
    <div>
      <p className="mb-2 text-xs text-muted-foreground">Peak day {formatUsd(peak)}</p>
      <div className={`flex h-40 items-end ${days.length > 45 ? "gap-px" : "gap-[3px]"}`}>
        {days.map((d) => {
          const height = d.cost_usd > 0 && peak > 0 ? Math.max((d.cost_usd / peak) * 100, 3) : 0;
          return (
            <div
              key={d.date}
              className="flex h-full flex-1 items-end"
              title={`${formatDay(d.date)}: ${formatUsd(d.cost_usd)}, ${d.requests} requests`}
            >
              <div
                className={`w-full rounded-t-sm ${d.cost_usd > 0 ? "bg-primary" : "bg-muted"}`}
                style={{ height: d.cost_usd > 0 ? `${height}%` : "2px" }}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex justify-between text-[11px] text-muted-foreground">
        <span>{formatDay(days[0].date)}</span>
        <span>{formatDay(days[days.length - 1].date)}</span>
      </div>
    </div>
  );
}

type BreakdownRow = { key: string; label: string; sub?: string; cost: number; requests: number };

function BreakdownList({ rows, loading }: { rows: BreakdownRow[]; loading: boolean }) {
  if (rows.length === 0) return <Placeholder loading={loading} />;
  const maxCost = Math.max(...rows.map((r) => r.cost));
  const maxRequests = Math.max(...rows.map((r) => r.requests));
  return (
    <ul className="space-y-3">
      {rows.map((r) => {
        // Rows that cost nothing (all cache hits, say) fall back to sizing by request count.
        const share = maxCost > 0 ? r.cost / maxCost : r.requests / (maxRequests || 1);
        return (
          <li key={r.key}>
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="truncate">
                {r.label}
                {r.sub && <span className="ml-2 text-xs text-muted-foreground">{r.sub}</span>}
              </span>
              <span className="shrink-0 tabular-nums">
                {formatUsd(r.cost)}
                <span className="ml-2 text-xs text-muted-foreground">{r.requests} req</span>
              </span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(share * 100, 2)}%` }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function BudgetCard({ budget, onSaved }: { budget: BudgetStatus | null; onSaved: (b: BudgetStatus) => void }) {
  const [amount, setAmount] = useState("");
  const [percent, setPercent] = useState("80");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!budget) return;
    setAmount(budget.threshold_amount !== null ? String(budget.threshold_amount) : "");
    setPercent(String(budget.notify_at_percent));
  }, [budget?.threshold_amount, budget?.notify_at_percent]);

  async function save(clear: boolean) {
    const value = clear ? null : Number(amount);
    const pct = Number(percent);
    if (!clear && (!Number.isFinite(value) || (value ?? 0) <= 0)) {
      setMessage("Enter an amount above 0.");
      return;
    }
    if (!Number.isInteger(pct) || pct < 1 || pct > 100) {
      setMessage("Notify percent must be a whole number from 1 to 100.");
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      const updated = await setBudget(value, pct);
      onSaved(updated);
      if (clear) setAmount("");
      setMessage(clear ? "Alert cleared." : "Alert saved.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not save");
    } finally {
      setSaving(false);
    }
  }

  const used = budget?.percent_used ?? 0;

  return (
    <section className="mb-6 rounded-xl border border-border bg-card p-4">
      <h2 className="text-sm font-medium">Monthly spend alert</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        A warning for yourself. It never blocks a request, since the spend is on your own provider accounts.
      </p>

      {budget && budget.threshold_amount !== null && (
        <div className="mt-4">
          <div className="flex justify-between text-sm">
            <span>{formatUsd(budget.month_spend)} this month</span>
            <span className="text-muted-foreground">of {formatUsd(budget.threshold_amount)}</span>
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-muted">
            <div
              className={`h-full rounded-full ${budget.state === "exceeded" ? "bg-destructive" : "bg-primary"}`}
              style={{ width: `${Math.min(used, 100)}%` }}
            />
          </div>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <label className="text-xs text-muted-foreground">
          Alert at (USD per month)
          <input
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            inputMode="decimal"
            placeholder="25"
            className="mt-1 block w-36 rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary/50"
          />
        </label>
        <label className="text-xs text-muted-foreground">
          Warn me at (% of alert)
          <input
            value={percent}
            onChange={(e) => setPercent(e.target.value)}
            inputMode="numeric"
            className="mt-1 block w-28 rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary/50"
          />
        </label>
        <button
          onClick={() => save(false)}
          disabled={saving}
          className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          Save
        </button>
        {budget?.threshold_amount !== null && budget?.threshold_amount !== undefined && (
          <button
            onClick={() => save(true)}
            disabled={saving}
            className="rounded-xl border border-border px-4 py-2 text-sm hover:bg-muted disabled:opacity-50"
          >
            Clear
          </button>
        )}
      </div>
      {message && <p className="mt-3 text-xs text-muted-foreground">{message}</p>}
    </section>
  );
}

function LogTable({ rows, loading }: { rows: UsageLogItem[]; loading: boolean }) {
  if (rows.length === 0) {
    return <p className="p-6 text-center text-sm text-muted-foreground">{loading ? "Loading..." : "No requests yet."}</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-muted-foreground">
          <tr>
            <th className="px-4 py-2 font-normal">Time</th>
            <th className="px-4 py-2 font-normal">Model</th>
            <th className="px-4 py-2 font-normal">Feature</th>
            <th className="px-4 py-2 text-right font-normal">Tokens in / out</th>
            <th className="px-4 py-2 text-right font-normal">Cost</th>
            <th className="px-4 py-2 text-right font-normal">Latency</th>
            <th className="px-4 py-2 font-normal">Notes</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="whitespace-nowrap px-4 py-2 text-muted-foreground">
                {new Date(r.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </td>
              <td className="whitespace-nowrap px-4 py-2">
                {r.model}
                <span className="ml-2 text-xs text-muted-foreground">{r.provider}</span>
              </td>
              <td className="whitespace-nowrap px-4 py-2 text-muted-foreground">{r.feature_tag ?? "untagged"}</td>
              <td className="whitespace-nowrap px-4 py-2 text-right tabular-nums">
                {r.input_tokens} / {r.output_tokens}
              </td>
              <td className="whitespace-nowrap px-4 py-2 text-right tabular-nums">{formatUsd(r.cost_usd)}</td>
              <td className="whitespace-nowrap px-4 py-2 text-right tabular-nums">{Math.round(r.latency_ms)} ms</td>
              <td className="whitespace-nowrap px-4 py-2">
                <div className="flex gap-1.5">
                  {r.cache_hit && <Pill text="cache" />}
                  {r.fallback_used && <Pill text="fallback" />}
                  {r.error && <Pill text="error" title={r.error} danger />}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Pill({ text, title, danger }: { text: string; title?: string; danger?: boolean }) {
  return (
    <span
      title={title}
      className={`rounded-full px-2 py-0.5 text-[11px] ${
        danger ? "bg-destructive/15 text-destructive" : "bg-muted text-muted-foreground"
      }`}
    >
      {text}
    </span>
  );
}

"use client";
import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  createExperiment,
  getExperimentResults,
  getStoredKey,
  listExperiments,
  listModels,
  listPrompts,
  stopExperiment,
  type ExperimentItem,
  type ExperimentResults,
  type ModelInfo,
  type NewVariant,
  type PromptItem,
  type VariantResult,
} from "@/lib/api";

const POLL_MS = 10000;
const TAG_OK = /^[a-z0-9_.-]{1,50}$/;
const VARIANT_OK = /^[a-z0-9_-]{1,50}$/;

function usd(n: number | null | undefined) {
  if (n === null || n === undefined) return "-";
  return `$${n.toFixed(n < 0.01 ? 5 : 4)}`;
}
function pct(n: number | null | undefined) {
  return n === null || n === undefined ? "-" : `${(n * 100).toFixed(1)}%`;
}
function ms(n: number | null | undefined) {
  return n === null || n === undefined ? "-" : `${Math.round(n)} ms`;
}
function num(n: number | null | undefined) {
  return n === null || n === undefined ? "-" : String(Math.round(n));
}

export default function ExperimentsPage() {
  const [hasKey, setHasKey] = useState<boolean | null>(null);
  const [experiments, setExperiments] = useState<ExperimentItem[]>([]);
  const [prompts, setPrompts] = useState<PromptItem[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setHasKey(!!getStoredKey());
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [e, p, m] = await Promise.all([listExperiments(), listPrompts(), listModels()]);
      setExperiments(e);
      setPrompts(p);
      setModels(m);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load experiments");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (hasKey) refresh();
    else if (hasKey === false) setLoading(false);
  }, [hasKey, refresh]);

  if (hasKey === false) {
    return (
      <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-3 px-5 text-foreground">
        <h1 className="text-2xl font-semibold">Experiments</h1>
        <p className="text-sm text-muted-foreground">Sign in with a gateway key to run experiments.</p>
        <Link href="/dashboard/keys" className="text-sm text-primary hover:underline">
          Get a key
        </Link>
      </div>
    );
  }

  return (
    <div className="h-screen overflow-y-auto">
      <div className="mx-auto max-w-5xl px-5 py-10 text-foreground">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold">Experiments</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Split the traffic of one feature between models or prompt versions and compare cost, speed and reliability.
            </p>
          </div>
          <button
            onClick={() => {
              setCreating(true);
              setSelected(null);
            }}
            className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
          >
            New experiment
          </button>
        </div>

        {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

        <div className="grid gap-6 md:grid-cols-[260px_1fr]">
          <aside className="rounded-xl border border-border bg-card">
            {experiments.length === 0 ? (
              <p className="p-4 text-sm text-muted-foreground">{loading ? "Loading..." : "No experiments yet."}</p>
            ) : (
              <ul className="divide-y divide-border">
                {experiments.map((e) => (
                  <li key={e.id}>
                    <button
                      onClick={() => {
                        setSelected(e.id);
                        setCreating(false);
                      }}
                      className={`block w-full px-4 py-3 text-left text-sm hover:bg-muted ${selected === e.id ? "bg-muted" : ""}`}
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="truncate">{e.name}</span>
                        <span
                          className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] ${
                            e.status === "active" ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground"
                          }`}
                        >
                          {e.status}
                        </span>
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                        {e.feature_tag} · {e.requests ?? 0} requests
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </aside>

          <main>
            {creating && (
              <CreateForm
                models={models}
                prompts={prompts}
                onCreated={async (id) => {
                  await refresh();
                  setCreating(false);
                  setSelected(id);
                }}
              />
            )}
            {!creating && selected && <ResultsPanel key={selected} id={selected} onChanged={refresh} />}
            {!creating && !selected && (
              <p className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
                Pick an experiment on the left, or start a new one.
              </p>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}

type Row = { name: string; percent: string; model: string; promptName: string; promptVersion: string };

const fieldClass =
  "mt-1 block w-full rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary/50";

function CreateForm({
  models,
  prompts,
  onCreated,
}: {
  models: ModelInfo[];
  prompts: PromptItem[];
  onCreated: (id: string) => void;
}) {
  const [name, setName] = useState("");
  const [tag, setTag] = useState("");
  const [rows, setRows] = useState<Row[]>([
    { name: "control", percent: "50", model: "", promptName: "", promptVersion: "" },
    { name: "treatment", percent: "50", model: "", promptName: "", promptVersion: "" },
  ]);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const total = rows.reduce((sum, r) => sum + (Number(r.percent) || 0), 0);

  function update(i: number, patch: Partial<Row>) {
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  }

  async function submit() {
    const cleanTag = tag.trim().toLowerCase();
    if (!name.trim()) return setMessage("Give the experiment a name.");
    if (!TAG_OK.test(cleanTag)) return setMessage("The feature tag can use lowercase letters, numbers, dots, dashes and underscores.");
    const names = rows.map((r) => r.name.trim().toLowerCase());
    if (names.some((n) => !VARIANT_OK.test(n))) return setMessage("Variant names can use lowercase letters, numbers, dashes and underscores.");
    if (new Set(names).size !== names.length) return setMessage("Variant names must be different.");
    const percents = rows.map((r) => Number(r.percent));
    if (percents.some((p) => !Number.isInteger(p) || p < 1 || p > 99)) return setMessage("Each split must be a whole number from 1 to 99.");
    if (total !== 100) return setMessage("The splits must add up to 100.");

    const variants: NewVariant[] = rows.map((r, i) => ({
      name: names[i],
      percent: percents[i],
      model: r.model || null,
      prompt_name: r.promptName || null,
      prompt_version: r.promptName && r.promptVersion ? Number(r.promptVersion) : null,
    }));

    setSaving(true);
    setMessage(null);
    try {
      const created = await createExperiment(name.trim(), cleanTag, variants);
      onCreated(created.id);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not create the experiment");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <h2 className="text-sm font-medium">New experiment</h2>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <label className="block text-xs text-muted-foreground">
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Short answers test" className={fieldClass} />
        </label>
        <label className="block text-xs text-muted-foreground">
          Feature tag it applies to
          <input value={tag} onChange={(e) => setTag(e.target.value)} placeholder="support_bot" className={fieldClass} />
        </label>
      </div>

      <div className="mt-6 space-y-3">
        {rows.map((r, i) => {
          const selectedPrompt = prompts.find((p) => p.name === r.promptName);
          return (
            <div key={i} className="rounded-xl border border-border p-3">
              <div className="grid gap-3 sm:grid-cols-[1fr_90px]">
                <label className="block text-xs text-muted-foreground">
                  Variant name
                  <input value={r.name} onChange={(e) => update(i, { name: e.target.value })} className={fieldClass} />
                </label>
                <label className="block text-xs text-muted-foreground">
                  Split %
                  <input
                    value={r.percent}
                    onChange={(e) => update(i, { percent: e.target.value })}
                    inputMode="numeric"
                    className={fieldClass}
                  />
                </label>
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                <label className="block text-xs text-muted-foreground">
                  Model
                  <select value={r.model} onChange={(e) => update(i, { model: e.target.value })} className={fieldClass}>
                    <option value="">Router default</option>
                    {models.map((m) => (
                      <option key={m.model} value={m.model}>
                        {m.model}
                        {m.connected ? "" : " (not connected)"}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block text-xs text-muted-foreground">
                  Prompt
                  <select
                    value={r.promptName}
                    onChange={(e) => update(i, { promptName: e.target.value, promptVersion: "" })}
                    className={fieldClass}
                  >
                    <option value="">No prompt</option>
                    {prompts.map((p) => (
                      <option key={p.name} value={p.name}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block text-xs text-muted-foreground">
                  Prompt version
                  <select
                    value={r.promptVersion}
                    onChange={(e) => update(i, { promptVersion: e.target.value })}
                    disabled={!selectedPrompt}
                    className={`${fieldClass} disabled:opacity-50`}
                  >
                    <option value="">{selectedPrompt ? `Latest (v${selectedPrompt.version}), pinned now` : "-"}</option>
                    {selectedPrompt &&
                      Array.from({ length: selectedPrompt.version }, (_, k) => selectedPrompt.version - k).map((v) => (
                        <option key={v} value={v}>
                          v{v}
                        </option>
                      ))}
                  </select>
                </label>
              </div>
              {rows.length > 2 && (
                <button
                  onClick={() => setRows((rs) => rs.filter((_, idx) => idx !== i))}
                  className="mt-3 text-xs text-muted-foreground hover:text-foreground"
                >
                  Remove variant
                </button>
              )}
            </div>
          );
        })}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        {rows.length < 4 && (
          <button
            onClick={() => setRows((rs) => [...rs, { name: `variant_${rs.length + 1}`, percent: "0", model: "", promptName: "", promptVersion: "" }])}
            className="rounded-xl border border-border px-4 py-2 text-sm hover:bg-muted"
          >
            Add variant
          </button>
        )}
        <span className={`text-xs ${total === 100 ? "text-muted-foreground" : "text-destructive"}`}>Total: {total}%</span>
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        A variant with no model and no prompt is the control: it runs exactly as the feature does today. The prompt version is
        fixed when you start, so publishing a newer one later does not change a running test.
      </p>

      <div className="mt-4 flex items-center gap-3">
        <button
          onClick={submit}
          disabled={saving}
          className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          Start experiment
        </button>
        {message && <p className="text-xs text-destructive">{message}</p>}
      </div>
    </section>
  );
}

function ResultsPanel({ id, onChanged }: { id: string; onChanged: () => void }) {
  const [data, setData] = useState<ExperimentResults | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await getExperimentResults(id));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load results");
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const active = data?.experiment.status === "active";
  useEffect(() => {
    if (!active) return;
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [active, load]);

  async function stop() {
    setStopping(true);
    try {
      await stopExperiment(id);
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not stop the experiment");
    } finally {
      setStopping(false);
    }
  }

  if (error && !data) return <p className="text-sm text-destructive">{error}</p>;
  if (!data) return <p className="text-sm text-muted-foreground">Loading...</p>;

  const exp = data.experiment;
  const anyLow = data.variants.some((v) => v.low_sample);
  const example = JSON.stringify(
    { messages: [{ role: "user", content: "Hello" }], feature_tag: exp.feature_tag, subject_id: "customer-123" },
    null,
    2,
  );

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-border bg-card p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-medium">{exp.name}</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Feature tag {exp.feature_tag} · started {new Date(exp.created_at).toLocaleDateString()} ·{" "}
              {exp.status === "active" ? "running" : `stopped ${exp.stopped_at ? new Date(exp.stopped_at).toLocaleDateString() : ""}`}
            </p>
          </div>
          {active && (
            <button
              onClick={stop}
              disabled={stopping}
              className="rounded-xl border border-border px-4 py-2 text-sm hover:bg-muted disabled:opacity-50"
            >
              Stop experiment
            </button>
          )}
        </div>
        {error && <p className="mt-3 text-xs text-destructive">{error}</p>}

        {data.total_requests === 0 ? (
          <p className="mt-6 text-sm text-muted-foreground">No requests yet. Results appear here as traffic arrives.</p>
        ) : (
          <>
            {anyLow && (
              <p className="mt-4 rounded-xl bg-muted p-3 text-xs text-muted-foreground">
                Some variants have fewer than {data.low_sample_threshold} requests. Differences this small are mostly noise, so wait for more traffic before
                trusting them.
              </p>
            )}
            <ResultsTable variants={data.variants} />
          </>
        )}
      </section>

      {active && (
        <section className="rounded-xl border border-border bg-card p-4">
          <h3 className="text-sm font-medium">Send traffic to it</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Chat requests with this feature tag join the test. Add a subject_id (your own end user id) so each person always gets the same
            variant. Without one, every request is assigned at random.
          </p>
          <pre className="mt-3 overflow-x-auto rounded-xl bg-muted p-3 text-xs">{example}</pre>
        </section>
      )}
    </div>
  );
}

function ResultsTable({ variants }: { variants: VariantResult[] }) {
  const rows: { label: string; hint?: string; cell: (v: VariantResult) => string }[] = [
    { label: "Split (set / seen)", cell: (v) => `${v.percent}% / ${v.observed_percent}%` },
    { label: "Requests", cell: (v) => String(v.requests) },
    { label: "People (with subject_id)", cell: (v) => String(v.subjects) },
    { label: "Success rate", hint: "Answered with no error and no fallback to another provider", cell: (v) => pct(v.success_rate) },
    { label: "Fallbacks", cell: (v) => String(v.fallbacks) },
    { label: "Cache hit rate", cell: (v) => pct(v.cache_hit_rate) },
    { label: "Avg cost per request", hint: "Only requests that reached a provider", cell: (v) => usd(v.avg_cost_usd) },
    { label: "Avg latency", hint: "Only requests that reached a provider", cell: (v) => ms(v.avg_latency_ms) },
    { label: "Median latency", cell: (v) => ms(v.p50_latency_ms) },
    { label: "Slowest 5% (p95)", cell: (v) => ms(v.p95_latency_ms) },
    { label: "Avg output tokens", cell: (v) => num(v.avg_output_tokens) },
    { label: "Total cost", cell: (v) => usd(v.cost_usd) },
  ];

  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border">
            <th className="px-3 py-2 text-xs font-normal text-muted-foreground" />
            {variants.map((v) => (
              <th key={v.name} className="px-3 py-2 align-top">
                <span className="block font-medium">{v.name}</span>
                <span className="block text-xs font-normal text-muted-foreground">{v.model ?? "router default"}</span>
                <span className="block text-xs font-normal text-muted-foreground">
                  {v.prompt_name ? `${v.prompt_name} v${v.prompt_version}` : "no prompt"}
                </span>
                {v.low_sample && (
                  <span className="mt-1 inline-block rounded-full bg-muted px-2 py-0.5 text-[11px] font-normal text-muted-foreground">
                    low sample
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((r) => (
            <tr key={r.label}>
              <td className="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground" title={r.hint}>
                {r.label}
              </td>
              {variants.map((v) => (
                <td key={v.name} className="whitespace-nowrap px-3 py-2 tabular-nums">
                  {r.cell(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

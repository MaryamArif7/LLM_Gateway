"use client";

import { useState } from "react";
import { compareModels } from "@/lib/api";
import { RouteTicket } from "@/components/RouteTicket";
import { MODELS } from "@/lib/models";

export default function ComparePage() {
  const [prompt, setPrompt] = useState("");
  const [selected, setSelected] = useState<string[]>([MODELS[0].id, MODELS[2].id, MODELS[4].id]);
  const [results, setResults] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);

  function toggle(id: string) {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((m) => m !== id) : prev.length < 4 ? [...prev, id] : prev
    );
  }

  async function run() {
    if (!prompt.trim() || selected.length === 0 || busy) return;
    setBusy(true);
    setResults(null);
    try {
      const data = await compareModels({ prompt, models: selected });
      setResults(data.results);
    } catch (e: any) {
      setResults([{ provider: "gateway", model: "-", error: e.message, content: null }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-6xl mx-auto px-6 py-6">
      <div className="flex items-center justify-between mb-1">
        <h1 className="font-mono text-sm text-ink">Compare mode</h1>
        <span className="text-xs font-mono text-danger/80 border border-danger/30 rounded px-2 py-0.5">
          calls {selected.length || "0"} provider{selected.length === 1 ? "" : "s"} directly — bypasses the router, {selected.length}× the cost of a routed message
        </span>
      </div>
      <p className="text-muted text-xs mb-4">
        Use this to sanity-check the router&apos;s decisions, not as your everyday chat.
      </p>

      <div className="flex flex-wrap gap-2 mb-3">
        {MODELS.map((m) => (
          <button
            key={m.id}
            onClick={() => toggle(m.id)}
            className={`px-2.5 py-1 rounded-md text-xs font-mono border transition-colors ${
              selected.includes(m.id)
                ? "border-route text-route bg-route/10"
                : "border-border text-muted hover:text-ink"
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      <div className="flex gap-2 mb-6">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Prompt to send to all selected models…"
          rows={2}
          className="flex-1 bg-panelraised border border-border rounded-md px-3 py-2 text-sm text-ink resize-none focus:outline-none focus:border-route"
        />
        <button
          onClick={run}
          disabled={busy}
          className="px-4 py-2 rounded-md bg-route text-panel font-medium text-sm disabled:opacity-40 whitespace-nowrap"
        >
          {busy ? "Running…" : "Compare all"}
        </button>
      </div>

      {results && (
        <div className={`grid gap-4`} style={{ gridTemplateColumns: `repeat(${results.length}, minmax(0, 1fr))` }}>
          {results.map((r, i) => (
            <div key={i} className="border border-border rounded-lg bg-panelraised p-4 flex flex-col gap-3">
              {r.error ? (
                <div className="text-danger text-sm font-mono">⚠ {r.error}</div>
              ) : (
                <>
                  <RouteTicket
                    provider={r.provider}
                    model={r.model}
                    tokens={{ in: r.input_tokens, out: r.output_tokens }}
                    costUsd={r.cost_usd}
                    latencyMs={r.latency_ms}
                  />
                  <div className="text-sm text-ink whitespace-pre-wrap">{r.content}</div>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

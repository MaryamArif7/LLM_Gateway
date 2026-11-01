"use client";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  createPrompt,
  getPromptVersions,
  getStoredKey,
  listModels,
  listPrompts,
  publishPromptVersion,
  type ModelInfo,
  type PromptItem,
} from "@/lib/api";

const PLACEHOLDER = /\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g;
const NAME_OK = /^[a-z0-9][a-z0-9_.-]{0,63}$/;

function variablesIn(template: string): string[] {
  const out: string[] = [];
  for (const m of template.matchAll(PLACEHOLDER)) {
    if (!out.includes(m[1])) out.push(m[1]);
  }
  return out;
}

export default function PromptsPage() {
  const [hasKey, setHasKey] = useState<boolean | null>(null);
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
      const [p, m] = await Promise.all([listPrompts(), listModels()]);
      setPrompts(p);
      setModels(m);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load prompts");
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
        <h1 className="text-2xl font-semibold">Prompts</h1>
        <p className="text-sm text-muted-foreground">Sign in with a gateway key to manage prompts.</p>
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
            <h1 className="text-2xl font-semibold">Prompts</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Versioned prompt templates. Each publish makes a new version, and old versions never change.
            </p>
          </div>
          <button
            onClick={() => {
              setCreating(true);
              setSelected(null);
            }}
            className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
          >
            New prompt
          </button>
        </div>

        {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

        <div className="grid gap-6 md:grid-cols-[240px_1fr]">
          <aside className="rounded-xl border border-border bg-card">
            {prompts.length === 0 ? (
              <p className="p-4 text-sm text-muted-foreground">{loading ? "Loading..." : "No prompts yet."}</p>
            ) : (
              <ul className="divide-y divide-border">
                {prompts.map((p) => (
                  <li key={p.name}>
                    <button
                      onClick={() => {
                        setSelected(p.name);
                        setCreating(false);
                      }}
                      className={`flex w-full items-center justify-between px-4 py-3 text-left text-sm hover:bg-muted ${
                        selected === p.name ? "bg-muted" : ""
                      }`}
                    >
                      <span className="truncate">{p.name}</span>
                      <span className="ml-2 shrink-0 text-xs text-muted-foreground">v{p.version}</span>
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
                onCreated={async (name) => {
                  await refresh();
                  setCreating(false);
                  setSelected(name);
                }}
              />
            )}
            {!creating && selected && (
              <PromptDetail key={selected} name={selected} models={models} onPublished={refresh} />
            )}
            {!creating && !selected && (
              <p className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
                Pick a prompt on the left, or create a new one.
              </p>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}

function ModelSelect({
  value,
  onChange,
  models,
}: {
  value: string;
  onChange: (v: string) => void;
  models: ModelInfo[];
}) {
  return (
    <select
      aria-label="Target model"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="mt-1 block w-full rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary/50"
    >
      <option value="">No preference (use the router)</option>
      {models.map((m) => (
        <option key={m.model} value={m.model}>
          {m.model}
          {m.connected ? "" : " (provider not connected)"}
        </option>
      ))}
    </select>
  );
}

function VariableChips({ template }: { template: string }) {
  const vars = useMemo(() => variablesIn(template), [template]);
  if (vars.length === 0) {
    return <p className="text-xs text-muted-foreground">No variables. Use {"{{name}}"} to add one.</p>;
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
      Variables:
      {vars.map((v) => (
        <span key={v} className="rounded-full bg-muted px-2 py-0.5">
          {v}
        </span>
      ))}
    </div>
  );
}

function CreateForm({ models, onCreated }: { models: ModelInfo[]; onCreated: (name: string) => void }) {
  const [name, setName] = useState("");
  const [template, setTemplate] = useState("");
  const [model, setModel] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function submit() {
    const clean = name.trim().toLowerCase();
    if (!NAME_OK.test(clean)) {
      setMessage("Use lowercase letters, numbers, dots, dashes or underscores, up to 64 characters.");
      return;
    }
    if (!template.trim()) {
      setMessage("Write the template text first.");
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      await createPrompt(clean, template, model || null);
      onCreated(clean);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not create the prompt");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <h2 className="text-sm font-medium">New prompt</h2>
      <div className="mt-4 space-y-4">
        <label className="block text-xs text-muted-foreground">
          Name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="support-greeting"
            className="mt-1 block w-full rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary/50"
          />
        </label>
        <label className="block text-xs text-muted-foreground">
          Template (sent as the system message)
          <textarea
            value={template}
            onChange={(e) => setTemplate(e.target.value)}
            rows={8}
            placeholder="You are a {{tone}} assistant for {{company}}."
            className="mt-1 block w-full rounded-xl border border-border bg-background px-3 py-2 font-mono text-sm text-foreground outline-none focus:border-primary/50"
          />
        </label>
        <VariableChips template={template} />
        <label className="block text-xs text-muted-foreground">
          Preferred model (optional)
          <ModelSelect value={model} onChange={setModel} models={models} />
        </label>
        <div className="flex items-center gap-3">
          <button
            onClick={submit}
            disabled={saving}
            className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            Create version 1
          </button>
          {message && <p className="text-xs text-destructive">{message}</p>}
        </div>
      </div>
    </section>
  );
}

function PromptDetail({
  name,
  models,
  onPublished,
}: {
  name: string;
  models: ModelInfo[];
  onPublished: () => void;
}) {
  const [versions, setVersions] = useState<PromptItem[]>([]);
  const [viewing, setViewing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [draftModel, setDraftModel] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const v = await getPromptVersions(name);
      setVersions(v);
      setViewing(v[0].version);
      setDraft(v[0].template);
      setDraftModel(v[0].target_model ?? "");
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load versions");
    }
  }, [name]);

  useEffect(() => {
    load();
  }, [load]);

  const current = versions.find((v) => v.version === viewing) ?? null;
  const latest = versions[0] ?? null;
  const unchanged = !!current && draft === current.template && draftModel === (current.target_model ?? "");

  function pick(v: PromptItem) {
    setViewing(v.version);
    setDraft(v.template);
    setDraftModel(v.target_model ?? "");
    setMessage(null);
  }

  async function publish() {
    if (!draft.trim()) {
      setMessage("The template cannot be empty.");
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      const created = await publishPromptVersion(name, draft, draftModel || null);
      await load();
      onPublished();
      setMessage(`Published version ${created.version}.`);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not publish");
    } finally {
      setSaving(false);
    }
  }

  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (!latest || !current) return <p className="text-sm text-muted-foreground">Loading...</p>;

  const exampleVars = Object.fromEntries(latest.variables.map((v) => [v, "..."]));
  const example = JSON.stringify(
    {
      messages: [{ role: "user", content: "Hello" }],
      prompt: name,
      ...(latest.variables.length ? { variables: exampleVars } : {}),
    },
    null,
    2,
  );

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-border bg-card p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-medium">{name}</h2>
          <span className="text-xs text-muted-foreground">
            {versions.length} version{versions.length === 1 ? "" : "s"}
          </span>
        </div>

        <div className="mt-4 flex flex-wrap gap-1.5" role="tablist" aria-label="Versions">
          {versions.map((v) => (
            <button
              key={v.version}
              role="tab"
              aria-selected={v.version === viewing}
              onClick={() => pick(v)}
              className={`rounded-full px-3 py-1 text-xs ${
                v.version === viewing ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              v{v.version}
              {v.version === latest.version ? " (latest)" : ""}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Version {current.version}, published {new Date(current.created_at).toLocaleString()}
          {current.target_model ? `, prefers ${current.target_model}` : ""}
        </p>

        <label className="mt-4 block text-xs text-muted-foreground">
          {current.version === latest.version ? "Edit, then publish as a new version" : "Start a new version from this old one"}
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={9}
            className="mt-1 block w-full rounded-xl border border-border bg-background px-3 py-2 font-mono text-sm text-foreground outline-none focus:border-primary/50"
          />
        </label>
        <div className="mt-2">
          <VariableChips template={draft} />
        </div>
        <label className="mt-4 block max-w-sm text-xs text-muted-foreground">
          Preferred model
          <ModelSelect value={draftModel} onChange={setDraftModel} models={models} />
        </label>
        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={publish}
            disabled={saving || unchanged}
            className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            Publish version {latest.version + 1}
          </button>
          {unchanged && <span className="text-xs text-muted-foreground">Change the text or model first.</span>}
          {message && <span className="text-xs text-muted-foreground">{message}</span>}
        </div>
      </section>

      <section className="rounded-xl border border-border bg-card p-4">
        <h3 className="text-sm font-medium">Use it from the API</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Send the name in a chat request. You get the latest version, or add prompt_version to pin one.
        </p>
        <pre className="mt-3 overflow-x-auto rounded-xl bg-muted p-3 text-xs">{example}</pre>
      </section>
    </div>
  );
}

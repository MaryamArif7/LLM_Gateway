"use client";
import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Trash2 } from "lucide-react";
import { getStoredKey, addProviderKey, listProviderKeys, removeProviderKey } from "@/lib/api";

const PROVIDERS = [
  { id: "openai", label: "OpenAI", placeholder: "sk-..." },
  { id: "anthropic", label: "Anthropic", placeholder: "sk-ant-..." },
  { id: "gemini", label: "Google Gemini", placeholder: "AIza..." },
  { id: "mistral", label: "Mistral", placeholder: "..." },
];

export default function ProvidersPage() {
  const [hasKey, setHasKey] = useState(true);
  const [connected, setConnected] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const key = getStoredKey();
    setHasKey(!!key);
    if (key) refresh();
  }, []);

  async function refresh() {
    try {
      setConnected(await listProviderKeys());
    } catch (e: any) {
      setError(e.message);
    }
  }

  if (!hasKey) {
    return (
      <div className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-3 px-5 text-center text-foreground">
        <p className="text-sm text-muted-foreground">You need a gateway key first.</p>
        <Link href="/dashboard/keys" className="text-sm font-medium underline underline-offset-2">
          Create one here
        </Link>
      </div>
    );
  }

  const connectedByProvider = Object.fromEntries(connected.map((c) => [c.provider, c]));

  return (
    <div className="mx-auto max-w-2xl px-5 py-10 text-foreground">
      <div className="mb-2 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Provider keys</h1>
        <Link href="/dashboard/keys" className="text-sm text-muted-foreground hover:text-foreground">
          ← Gateway keys
        </Link>
      </div>
      <p className="mb-6 text-sm text-muted-foreground">
        Connect your own OpenAI, Anthropic, Gemini, or Mistral key. The gateway routes and streams your requests,
        but every call is billed to your own provider account, not ours.
      </p>

      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

      <div className="grid gap-3">
        {PROVIDERS.map((p) => (
          <ProviderCard
            key={p.id}
            provider={p}
            existing={connectedByProvider[p.id]}
            onChange={refresh}
            onError={setError}
          />
        ))}
      </div>
    </div>
  );
}

function ProviderCard({ provider, existing, onChange, onError }: any) {
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleConnect() {
    if (!value.trim()) return;
    setSaving(true);
    try {
      await addProviderKey(provider.id, value.trim());
      setValue("");
      onChange();
    } catch (e: any) {
      onError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleRemove() {
    try {
      await removeProviderKey(existing.id);
      onChange();
    } catch (e: any) {
      onError(e.message);
    }
  }

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-sm font-medium">{provider.label}</p>
        {existing && (
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            connected · {existing.key_last4}
          </span>
        )}
      </div>

      {existing ? (
        <button
          onClick={handleRemove}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-destructive"
        >
          <Trash2 size={12} /> Remove
        </button>
      ) : (
        <div className="flex gap-2">
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={provider.placeholder}
            type="password"
            className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary/50"
          />
          <button
            onClick={handleConnect}
            disabled={saving}
            className="rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            Connect
          </button>
        </div>
      )}
    </div>
  );
}

"use client";
import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Copy, Trash2 } from "lucide-react";
import {
  getStoredKey,
  setStoredKey,
  clearStoredKey,
  signup,
  createGatewayKey,
  listGatewayKeys,
  revokeGatewayKey,
} from "@/lib/api";

export default function KeysPage() {
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [newKeyName, setNewKeyName] = useState("");
  const [keys, setKeys] = useState<any[]>([]);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setActiveKey(getStoredKey());
  }, []);

  useEffect(() => {
    if (activeKey) refreshKeys();
  }, [activeKey]);

  async function refreshKeys() {
    try {
      setKeys(await listGatewayKeys());
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function handleSignup() {
    if (!email.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await signup(email.trim());
      setStoredKey(result.raw_key);
      setActiveKey(result.raw_key);
      setRevealedKey(result.raw_key);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleCreateKey() {
    setLoading(true);
    setError(null);
    try {
      const result = await createGatewayKey(newKeyName.trim() || "Default key");
      setRevealedKey(result.raw_key);
      setNewKeyName("");
      await refreshKeys();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleRevoke(id: string) {
    try {
      await revokeGatewayKey(id);
      await refreshKeys();
    } catch (e: any) {
      setError(e.message);
    }
  }

  function handleUseThisBrowser() {
    clearStoredKey();
    setActiveKey(null);
    setKeys([]);
  }


  if (!activeKey) {
    return (
      <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 px-5 text-foreground">
        <h1 className="text-2xl font-semibold">Get your gateway key</h1>
        <p className="text-sm text-muted-foreground">
          No password needed for now, just an email to identify your account. This creates your first key.
        </p>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          className="rounded-xl border border-border bg-card px-4 py-2.5 text-sm outline-none focus:border-primary/50"
        />
        {error && <p className="text-sm text-destructive">{error}</p>}
        <button
          onClick={handleSignup}
          disabled={loading || !email.trim()}
          className="rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {loading ? "Creating..." : "Create my key"}
        </button>
        <p className="text-xs text-muted-foreground">
          Already have a key from before? Paste it directly using the field below.
        </p>
        <PasteExistingKey onSet={(k) => setActiveKey(k)} />
      </div>
    );
  }


  return (
    <div className="mx-auto max-w-2xl px-5 py-10 text-foreground">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Gateway keys</h1>
        <Link href="/dashboard/providers" className="text-sm text-muted-foreground hover:text-foreground">
          Connect providers →
        </Link>
      </div>

      {revealedKey && (
        <div className="mb-6 rounded-xl border border-primary/40 bg-primary/5 p-4">
          <p className="mb-2 text-sm font-medium">Save this key now, it won't be shown again:</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 overflow-x-auto rounded-lg bg-card px-3 py-2 text-sm">{revealedKey}</code>
            <button
              onClick={() => navigator.clipboard?.writeText(revealedKey)}
              className="rounded-lg border border-border p-2 hover:bg-muted"
            >
              <Copy size={14} />
            </button>
          </div>
        </div>
      )}

      <div className="mb-6 flex gap-2">
        <input
          value={newKeyName}
          onChange={(e) => setNewKeyName(e.target.value)}
          placeholder="Key name (optional)"
          className="flex-1 rounded-xl border border-border bg-card px-4 py-2.5 text-sm outline-none focus:border-primary/50"
        />
        <button
          onClick={handleCreateKey}
          disabled={loading}
          className="rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          Create key
        </button>
      </div>

      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

      <div className="divide-y divide-border rounded-xl border border-border">
        {keys.length === 0 && (
          <p className="p-4 text-sm text-muted-foreground">No keys yet, create one above.</p>
        )}
        {keys.map((k) => (
          <div key={k.id} className="flex items-center justify-between p-4">
            <div>
              <p className="text-sm font-medium">{k.name}</p>
              <p className="text-xs text-muted-foreground">
                {k.status} · created {new Date(k.created_at).toLocaleDateString()}
                {k.last_used_at ? ` · last used ${new Date(k.last_used_at).toLocaleDateString()}` : ""}
              </p>
            </div>
            {k.status === "active" && (
              <button
                onClick={() => handleRevoke(k.id)}
                className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-destructive"
              >
                <Trash2 size={14} />
              </button>
            )}
          </div>
        ))}
      </div>

      <button onClick={handleUseThisBrowser} className="mt-6 text-xs text-muted-foreground underline">
        Sign out of this browser
      </button>
    </div>
  );
}

function PasteExistingKey({ onSet }: { onSet: (key: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <div className="flex gap-2">
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="gw_..."
        className="flex-1 rounded-xl border border-border bg-card px-3 py-2 text-sm outline-none focus:border-primary/50"
      />
      <button
        onClick={() => {
          if (!value.trim()) return;
          setStoredKey(value.trim());
          onSet(value.trim());
        }}
        className="rounded-xl border border-border px-3 py-2 text-sm hover:bg-muted"
      >
        Use
      </button>
    </div>
  );
}

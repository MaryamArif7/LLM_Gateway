

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
const STORAGE_KEY = "gateway_api_key";

export function getStoredKey(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(STORAGE_KEY);
}

export function setStoredKey(key: string) {
  window.localStorage.setItem(STORAGE_KEY, key);
}

export function clearStoredKey() {
  window.localStorage.removeItem(STORAGE_KEY);
}

function authHeaders(): Record<string, string> {
  const key = getStoredKey();
  return key ? { Authorization: `Bearer ${key}` } : {};
}

async function request(path: string, options: RequestInit = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...options.headers,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}



export function signup(email: string) {
  return request(`/api/auth/signup?email=${encodeURIComponent(email)}`, { method: "POST" });
}

export function createGatewayKey(name: string) {
  return request("/api/keys", { method: "POST", body: JSON.stringify({ name }) });
}

export function listGatewayKeys() {
  return request("/api/keys");
}

export function revokeGatewayKey(id: string) {
  return request(`/api/keys/${id}`, { method: "DELETE" });
}



export function addProviderKey(provider: string, apiKey: string) {
  return request("/api/provider-keys", { method: "POST", body: JSON.stringify({ provider, api_key: apiKey }) });
}

export function listProviderKeys() {
  return request("/api/provider-keys");
}

export function removeProviderKey(id: string) {
  return request(`/api/provider-keys/${id}`, { method: "DELETE" });
}



export type ChatStreamHandlers = {
  onMeta?: (data: any) => void;
  onDelta?: (text: string) => void;
  onDone?: (data: any) => void;
  onError?: (message: string) => void;
};

export async function streamChat(
  messages: { role: string; content: string }[],
  handlers: ChatStreamHandlers,
) {
  const res = await fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ messages }),
  });

  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({}));
    handlers.onError?.(body.detail || `Request failed: ${res.status}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

   
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";

    for (const chunk of chunks) {
      const eventLine = chunk.split("\n").find((l) => l.startsWith("event:"));
      const dataLine = chunk.split("\n").find((l) => l.startsWith("data:"));
      if (!eventLine || !dataLine) continue;

      const event = eventLine.replace("event:", "").trim();
      const data = JSON.parse(dataLine.replace("data:", "").trim());

      if (event === "meta") handlers.onMeta?.(data);
      else if (event === "delta") handlers.onDelta?.(data.text);
      else if (event === "done") handlers.onDone?.(data);
      else if (event === "error" || event === "provider_error") handlers.onError?.(data.message || data.error);
    }
  }
}
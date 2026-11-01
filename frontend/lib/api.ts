

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



export type UsageTotals = {
  requests: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  avg_latency_ms: number;
  cache_hits: number;
  cache_hit_rate: number;
  fallbacks: number;
  errors: number;
};

export type ModelUsage = {
  provider: string;
  model: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
};

export type FeatureUsage = {
  feature: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
};

export type DayUsage = { date: string; requests: number; tokens: number; cost_usd: number };

export type UsageSummary = {
  range: { from: string; to: string | null };
  feature: string | null;
  totals: UsageTotals;
  by_model: ModelUsage[];
  by_feature: FeatureUsage[];
  by_day: DayUsage[];
  available_features: string[];
  freshness: UsageFreshness;
};
export type UsageFreshness = {
  pipeline: "direct" | "kafka";
  last_event_at: string | null;
  last_ingest_lag_seconds: number | null;
};
export type UsageLogItem = {
  id: string;
  created_at: string;
  provider: string;
  model: string;
  feature_tag: string | null;
  classification: string | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms: number;
  cache_hit: boolean;
  fallback_used: boolean;
  error: string | null;
};

export type UsageLogPage = { items: UsageLogItem[]; next_cursor: string | null };

export type BudgetStatus = {
  threshold_amount: number | null;
  notify_at_percent: number;
  period: string;
  period_start: string;
  month_spend: number;
  percent_used: number | null;
  state: "none" | "ok" | "warning" | "exceeded";
};

export function getUsageSummary(params: { feature?: string; from?: string; to?: string } = {}): Promise<UsageSummary> {
  const q = new URLSearchParams();
  if (params.feature) q.set("feature", params.feature);
  if (params.from) q.set("from", params.from);
  if (params.to) q.set("to", params.to);
  return request(`/api/usage/summary?${q.toString()}`);
}

export function getUsageLogs(params: { limit?: number; cursor?: string | null; feature?: string } = {}): Promise<UsageLogPage> {
  const q = new URLSearchParams();
  if (params.limit) q.set("limit", String(params.limit));
  if (params.cursor) q.set("cursor", params.cursor);
  if (params.feature) q.set("feature", params.feature);
  return request(`/api/usage/logs?${q.toString()}`);
}

export function getBudget(): Promise<BudgetStatus> {
  return request("/api/usage/budget");
}

export function setBudget(thresholdAmount: number | null, notifyAtPercent: number): Promise<BudgetStatus> {
  return request("/api/usage/budget", {
    method: "PUT",
    body: JSON.stringify({ threshold_amount: thresholdAmount, notify_at_percent: notifyAtPercent }),
  });
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
  options: { featureTag?: string } = {},
) {
  const res = await fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ messages, ...(options.featureTag ? { feature_tag: options.featureTag } : {}) }),
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
export type ModelInfo = { model: string; provider: string; connected: boolean };

export type PromptItem = {
  name: string;
  version: number;
  template: string;
  target_model: string | null;
  variables: string[];
  created_at: string;
  version_count?: number;
};

export type VariantDef = {
  name: string;
  percent: number;
  model: string | null;
  prompt_name: string | null;
  prompt_version: number | null;
};

export type ExperimentItem = {
  id: string;
  name: string;
  feature_tag: string;
  variants: VariantDef[];
  status: "active" | "stopped";
  created_at: string;
  stopped_at: string | null;
  requests?: number;
};

export type VariantResult = VariantDef & {
  requests: number;
  observed_percent: number;
  subjects: number;
  errors: number;
  fallbacks: number;
  cache_hits: number;
  success_rate: number | null;
  cache_hit_rate: number | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
  live_requests: number;
  avg_cost_usd: number | null;
  avg_latency_ms: number | null;
  avg_output_tokens: number | null;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  low_sample: boolean;
};

export type ExperimentResults = {
  experiment: ExperimentItem;
  total_requests: number;
  low_sample_threshold: number;
  variants: VariantResult[];
};

export type NewVariant = {
  name: string;
  percent: number;
  model?: string | null;
  prompt_name?: string | null;
  prompt_version?: number | null;
};

export function listModels(): Promise<ModelInfo[]> {
  return request("/api/models");
}

export function listPrompts(): Promise<PromptItem[]> {
  return request("/api/prompts");
}

export function getPromptVersions(name: string): Promise<PromptItem[]> {
  return request(`/api/prompts/${encodeURIComponent(name)}/versions`);
}

export function createPrompt(name: string, template: string, targetModel: string | null): Promise<PromptItem> {
  return request("/api/prompts", {
    method: "POST",
    body: JSON.stringify({ name, template, target_model: targetModel }),
  });
}

export function publishPromptVersion(name: string, template: string, targetModel: string | null): Promise<PromptItem> {
  return request(`/api/prompts/${encodeURIComponent(name)}/versions`, {
    method: "POST",
    body: JSON.stringify({ template, target_model: targetModel }),
  });
}

export function listExperiments(): Promise<ExperimentItem[]> {
  return request("/api/experiments");
}

export function createExperiment(name: string, featureTag: string, variants: NewVariant[]): Promise<ExperimentItem> {
  return request("/api/experiments", {
    method: "POST",
    body: JSON.stringify({ name, feature_tag: featureTag, variants }),
  });
}

export function stopExperiment(id: string): Promise<ExperimentItem> {
  return request(`/api/experiments/${id}/stop`, { method: "POST" });
}

export function getExperimentResults(id: string): Promise<ExperimentResults> {
  return request(`/api/experiments/${id}/results`);
}

export type ProviderStatusName = "up" | "degraded" | "down" | "recovering" | "unknown";

export type ProviderStatus = {
  provider: string;
  status: ProviderStatusName;
  circuit: "closed" | "open" | "half_open";
  reason: string;
  window_seconds: number;
  successes: number;
  upstream_failures: number;
  client_failures: number;
  upstream_failure_rate: number | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  retry_in_seconds: number | null;
  consecutive_trips: number;
};

export type ProviderHealth = { updated_at: string; providers: ProviderStatus[] };

export function getProviderHealth(): Promise<ProviderHealth> {
  return request("/api/health/providers");
}


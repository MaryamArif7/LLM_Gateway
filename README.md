# LLM Gateway ->in progress

A multi-provider LLM gateway: routed chat with automatic model selection and
fallback, plus a separate side-by-side comparison mode. Built as a from-scratch
implementation of what production LLM routers (LiteLLM, RouteLLM, Bifrost)
solve, at a scope one person can actually build and understand end to end.

## Architecture

```
Next.js (chat + compare UI)
        │
        ▼
FastAPI Gateway
  ├─ rate limit (Redis, fixed window per client)
  ├─ cache check (Redis, SHA-256 fingerprint of request)
  ├─ router (heuristic classifier → model selection)
  ├─ provider adapters (OpenAI / Anthropic / Gemini, normalized interface)
  │    └─ fallback chain: try next provider on failure
  ├─ SSE streaming back to client
  └─ request log (Postgres) → tokens, cost, latency, routing reason
```

**Chat** (`Send` button) always goes through the router — one model is picked
per request based on a heuristic classification of the prompt (code / complex
/ long-context / simple), with an ordered fallback chain if that provider's
call fails.

**Compare** (`/compare`) deliberately bypasses the router — it fires the
prompt at every selected model in parallel. This is not the default chat
experience; it's the tool you use to sanity-check the router's decisions
(the UI flags the extra cost explicitly).


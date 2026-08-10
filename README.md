# LLM Gateway

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

## Local setup

### 1. Backend + infra (Docker)

```bash
cd llm-gateway
cp backend/.env.example backend/.env
# fill in OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY in backend/.env
docker compose up --build
```

Backend runs at `http://localhost:8000`. Postgres tables are created
automatically on startup (`init_db()` — swap for Alembic once the schema needs
to evolve without dropping data).

### 2. Frontend (Next.js, run separately for fast local dev)

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Frontend runs at `http://localhost:3000`.

## What's implemented (Milestones 1–4)

- [x] Provider adapters for OpenAI, Anthropic, Gemini — normalized `chat` /
      `chat_stream` interface, per-model cost tables
- [x] Heuristic router: classifies prompt → picks ordered (provider, model)
      fallback chain
- [x] Redis response cache (SHA-256 request fingerprint) + fixed-window rate
      limiter
- [x] Postgres logging of every request: tokens, cost, latency, classification,
      cache/fallback flags
- [x] SSE streaming chat endpoint with live fallback on provider failure
- [x] Compare endpoint: parallel calls across up to 4 models, no routing
- [x] Next.js chat UI: streaming, manual model override, per-message "routing
      ticket" showing provider/model/reason/cost/latency
- [x] Next.js compare UI: side-by-side columns, explicit cost warning

## Known gaps / good next steps

- **Rate limiter is fixed-window**, not sliding — can let ~2x burst through at
  window edges. Token bucket or sliding-window log is the natural upgrade.
- **No auth yet** — rate limiting is keyed by client IP. Add API keys /
  JWT + per-user budgets for Milestone 5.
- **Classifier is heuristic (regex/keyword)**, not learned — intentional for
  v1 (explainable, free, fast). Once you have labeled traffic, an
  embeddings + small classifier model (see RouteLLM's approach) is the
  upgrade path — swap the internals of `router/classifier.py` without
  touching anything that calls it.
- **No prompt versioning / A/B testing / Kafka / Grafana / Kubernetes yet** —
  these are the Milestone 5 items. Recommend adding them incrementally
  rather than all at once; see the conversation history in this project for
  the reasoning behind that sequencing.
- **`/api/stats` is a placeholder** for the observability dashboard — good
  enough for a quick in-app panel, but a real Grafana setup should read from
  Kafka-streamed events, not query Postgres directly, once volume grows.

## Load-testing the rate limiter (worth doing early)

Since the fixed-window limiter has a known edge-burst issue, prove it to
yourself before building on top of it:

```bash
# hammer the chat endpoint with concurrent requests, watch for over-admission
# at the minute boundary
```

Building a small script for this (e.g. with `httpx` + `asyncio.gather`) is a
good first "break my own system" exercise — see the earlier discussion on why
this teaches more than adding another tech to the stack.

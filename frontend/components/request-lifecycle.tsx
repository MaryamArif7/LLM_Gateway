"use client"

import { useEffect, useState } from "react"
import { Database, Gauge, Repeat, TrendingDown } from "lucide-react"

type Session = {
  tag: string
  prompt: string
  steps: string[]
  provider: "OpenAI" | "Anthropic" | "Google" | "Cache"
  model: string
  latency: string
  status: number
}

const SESSIONS: Session[] = [
  {
    tag: "complex",
    prompt: "weigh 3 market-entry strategies, show trade-offs",
    steps: ["classify", "cache check", "route", "fallback ready"],
    provider: "Anthropic",
    model: "claude-opus-4.8",
    latency: "2.38s",
    status: 200,
  },
  {
    tag: "simple",
    prompt: "summarize this changelog in two lines",
    steps: ["classify", "route"],
    provider: "OpenAI",
    model: "gpt-4o-mini",
    latency: "0.41s",
    status: 200,
  },
  {
    tag: "code",
    prompt: "refactor this handler to async / await",
    steps: ["classify", "cache check", "route"],
    provider: "Google",
    model: "gemini-2.5-pro",
    latency: "1.12s",
    status: 200,
  },
  {
    tag: "cached",
    prompt: "what is our refund policy?",
    steps: ["classify", "cache check"],
    provider: "Cache",
    model: "cache-hit",
    latency: "0.03s",
    status: 200,
  },
]

const PROVIDERS = ["OpenAI", "Anthropic", "Google"] as const

const stats = [
  { icon: Database, label: "cache hit rate", value: "41%" },
  { icon: Gauge, label: "p50 latency", value: "480ms" },
  { icon: Repeat, label: "fallbacks fired", value: "12" },
  { icon: TrendingDown, label: "cost vs. single-model", value: "-34%" },
]

export function RequestLifecycle() {
  const [idx, setIdx] = useState(0)
  // phase: 0 incoming, 1..n step active, n+1 resolved
  const [phase, setPhase] = useState(0)
  const [reduced, setReduced] = useState(false)

  const session = SESSIONS[idx]
  const totalPhases = session.steps.length + 2 // incoming + steps + resolved

  useEffect(() => {
    setReduced(window.matchMedia("(prefers-reduced-motion: reduce)").matches)
  }, [])

  useEffect(() => {
    if (reduced) {
      setPhase(totalPhases - 1)
      return
    }
    const id = setInterval(() => {
      setPhase((p) => {
        if (p >= totalPhases - 1) {
          setIdx((i) => (i + 1) % SESSIONS.length)
          return 0
        }
        return p + 1
      })
    }, 900)
    return () => clearInterval(id)
  }, [reduced, totalPhases, idx])

  const resolved = phase >= totalPhases - 1
  const activeStep = phase - 1 // which step index is active/complete

  return (
    <div className="mx-auto w-full max-w-5xl">
      {/* terminal log line */}
      <div className="rounded-t-xl border border-border bg-card/60 px-4 py-2.5 font-mono text-xs backdrop-blur-sm">
        <span className="text-muted-foreground">POST </span>
        <span className="text-foreground">/v1/chat </span>
        <span className="text-primary">tag:{session.tag}</span>
        <span className="text-muted-foreground"> {"→"} </span>
        <span className={resolved ? "text-foreground" : "text-muted-foreground/40"}>{session.model} </span>
        <span className={resolved ? "text-accent" : "text-muted-foreground/40"}>{session.status} </span>
        <span className={resolved ? "text-muted-foreground" : "text-muted-foreground/40"}>{session.latency}</span>
      </div>

      {/* main card */}
      <div className="rounded-b-xl border border-t-0 border-border bg-card/40 p-5 backdrop-blur-sm md:p-7">
        {/* incoming */}
        <div className="mb-3 flex items-center justify-between">
          <span className="text-xs uppercase tracking-widest text-muted-foreground">incoming request</span>
          <span className="rounded-md border border-primary/40 bg-primary/10 px-2 py-0.5 font-mono text-[11px] text-primary">
            {session.tag}
          </span>
        </div>
        <div
          key={session.prompt}
          className="rounded-lg border border-border bg-background/50 px-4 py-3 font-mono text-sm text-foreground/90"
        >
          {'"'}
          {session.prompt}
          {'"'}
        </div>

        {/* pipeline row */}
        <div className="mt-6 flex flex-col gap-4 md:flex-row md:items-stretch">
          {/* your app */}
          <div className="flex shrink-0 items-center justify-center rounded-xl border border-border bg-background/50 px-4 py-3 text-xs font-medium text-muted-foreground md:w-24">
            your app
          </div>

          {/* steps */}
          <div className="relative flex flex-1 items-center">
            {/* base rail */}
            <div className="absolute left-0 right-0 top-1/2 h-px -translate-y-1/2 bg-border" />
            {/* traveling packets of light */}
            <div className="pointer-events-none absolute left-0 right-0 top-1/2 h-px">
              <span className="gw-packet gw-dot-1" aria-hidden="true" />
              <span className="gw-packet gw-dot-2" aria-hidden="true" />
            </div>
            <div className="relative z-10 flex w-full flex-wrap items-center gap-2">
              {session.steps.map((step, i) => {
                const done = resolved || i <= activeStep
                const isActive = !resolved && i === activeStep
                return (
                  <span
                    key={step}
                    className={[
                      "flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-all duration-300",
                      done
                        ? "border-primary/50 bg-primary/10 text-foreground"
                        : "border-border bg-background/60 text-muted-foreground/60",
                      isActive ? "scale-105 shadow-[0_0_20px_-4px] shadow-primary/50" : "",
                    ].join(" ")}
                  >
                    <span
                      className={[
                        "h-1.5 w-1.5 rounded-full transition-colors",
                        done ? "bg-accent" : "bg-muted-foreground/40",
                        isActive ? "animate-pulse" : "",
                      ].join(" ")}
                    />
                    {step}
                  </span>
                )
              })}
            </div>
          </div>

          {/* providers */}
          <div className="flex shrink-0 flex-col gap-2 md:w-28">
            {PROVIDERS.map((p) => {
              const picked = resolved && session.provider === p
              return (
                <span
                  key={p}
                  className={[
                    "rounded-lg border px-3 py-1.5 text-center text-xs transition-all duration-300",
                    picked
                      ? "gw-resolved-ring scale-105 border-accent/60 bg-accent/15 text-accent shadow-[0_0_20px_-6px] shadow-accent/60"
                      : "border-border bg-background/50 text-muted-foreground/70",
                  ].join(" ")}
                >
                  {p}
                </span>
              )
            })}
          </div>
        </div>

        {/* resolved footer */}
        <div className="mt-6 flex items-center justify-between border-t border-border pt-4 font-mono text-xs">
          <span className={resolved ? "text-foreground" : "text-muted-foreground/40"}>
            <span className="text-muted-foreground">resolved {"→"} </span>
            {session.model}
          </span>
          <span className={resolved ? "text-muted-foreground" : "text-muted-foreground/40"}>{session.latency}</span>
        </div>
      </div>

      {/* stat cards */}
      <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {stats.map((s) => (
          <div key={s.label} className="rounded-xl border border-border bg-card/40 p-4 backdrop-blur-sm">
            <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <s.icon className="h-3.5 w-3.5" />
              {s.label}
            </span>
            <p className="mt-1.5 font-mono text-2xl font-semibold tabular-nums text-foreground">{s.value}</p>
          </div>
        ))}
      </div>

    
    </div>
  )
}

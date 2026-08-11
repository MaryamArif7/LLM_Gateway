"use client";
import React, { useEffect, useRef, useState } from "react";
import { ArrowUp, Sparkles, Copy, Square } from "lucide-react";

const SUGGESTIONS = [
  "Summarize a long article",
  "Debug a stack trace",
  "Plan a weekend trip",
  "Explain a concept simply",
];

export default function ChatPage() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [routing, setRouting] = useState(false);
  const scrollRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, routing]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [input]);

  function send(text) {
    if (!text.trim() || routing) return;

    setInput("");
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  }

  return (
    <div className="relative flex h-screen w-full flex-col bg-background text-foreground">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-[0.06]"
        style={{
          backgroundImage:
            "linear-gradient(var(--color-border) 1px, transparent 1px), linear-gradient(90deg, var(--color-border) 1px, transparent 1px)",
          backgroundSize: "44px 44px",
        }}
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-40 left-1/2 h-[520px] w-[820px] -translate-x-1/2 rounded-full opacity-30 blur-3xl"
        style={{
          background:
            "radial-gradient(closest-side, var(--color-glow), transparent 70%)",
        }}
      />

      <header className="relative flex shrink-0 items-center justify-between border-b border-border px-5 py-3">
        <div className="flex items-center gap-2 text-sm font-medium">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground">
            <Sparkles size={13} />
          </span>
          Gateway
        </div>
       
      </header>

      <div ref={scrollRef} className="relative flex-1 overflow-y-auto">
        <div className="mx-auto flex min-h-full max-w-2xl flex-col gap-7 px-5 py-10">
          {messages.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center text-center">
              <h1 className="text-balance text-3xl font-semibold tracking-tight">
                Ask it <span className="text-primary text-glow">anything</span>.
              </h1>
              <p className="mt-2 max-w-sm text-pretty text-sm leading-relaxed text-muted-foreground">
                Every message gets classified and routed to the model built for
                that kind of request.
              </p>
              <div className="mt-8 grid w-full max-w-md grid-cols-1 gap-2 sm:grid-cols-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="rounded-xl border border-border px-3.5 py-2.5 text-left text-sm text-muted-foreground transition-colors hover:border-primary/40 hover:bg-muted hover:text-foreground"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m, idx) =>
              m.role === "user" ? (
                <div key={idx} className="flex justify-end">
                  <div className="max-w-[75%] rounded-3xl bg-muted px-4 py-2.5 text-[15px] leading-relaxed text-foreground">
                    {m.content}
                  </div>
                </div>
              ) : (
                <div key={idx} className="group flex gap-3">
                  <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
                    <Sparkles size={13} />
                  </span>
                  <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                    <span className="font-mono text-xs text-muted-foreground">
                      {m.meta?.model}
                      {m.meta?.latency != null ? ` · ${m.meta.latency}ms` : ""}
                      {m.meta?.cacheHit ? " · cache hit" : ""}
                    </span>
                    <div className="text-[15px] leading-relaxed text-foreground">
                      {m.content}
                      {m.streaming && (
                        <span className="ml-0.5 inline-block h-4 w-[2px] -translate-y-[1px] animate-pulse bg-primary align-middle" />
                      )}
                    </div>
                    {!m.streaming && (
                      <button
                        className="mt-1 flex w-fit items-center gap-1.5 rounded-md px-1.5 py-1 text-xs text-muted-foreground opacity-0 transition-opacity hover:bg-muted hover:text-foreground group-hover:opacity-100"
                        onClick={() =>
                          navigator.clipboard?.writeText(m.content)
                        }
                      >
                        <Copy size={12} />
                        Copy
                      </button>
                    )}
                  </div>
                </div>
              ),
            )
          )}

          {routing && (
            <div className="flex items-center gap-3">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
                <Sparkles size={13} />
              </span>
              <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.3s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.15s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary" />
              </span>
            </div>
          )}
        </div>
      </div>

      <div className="relative shrink-0 px-5 pb-6 pt-2">
        <div className="mx-auto max-w-2xl">
          <div className="flex items-end gap-2 rounded-[26px] border border-border bg-card px-4 py-2.5 shadow-sm transition-colors focus-within:border-primary/50">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              placeholder="Message the gateway..."
              className="max-h-[200px] flex-1 resize-none bg-transparent py-1.5 text-[15px] leading-relaxed text-foreground placeholder-muted-foreground outline-none"
            />
            <button
              onClick={() => (routing ? setRouting(false) : send(input))}
              disabled={!routing && !input.trim()}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-all disabled:bg-muted disabled:text-muted-foreground"
            >
              {routing ? <Square size={13} /> : <ArrowUp size={16} />}
            </button>
          </div>
        
        </div>
      </div>
    </div>
  );
}

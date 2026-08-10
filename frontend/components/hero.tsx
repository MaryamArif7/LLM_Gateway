import { Button } from "@/components/ui/button"
import { RequestLifecycle } from "@/components/request-lifecycle"
import { ArrowRight } from "lucide-react"

export function Hero() {
  return (
    <section className="relative overflow-hidden">
      {/* ambient grid */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 grid-fade opacity-[0.06]"
        style={{
          backgroundImage:
            "linear-gradient(var(--color-border) 1px, transparent 1px), linear-gradient(90deg, var(--color-border) 1px, transparent 1px)",
          backgroundSize: "44px 44px",
        }}
      />
      {/* ambient glow */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-40 left-1/2 h-[520px] w-[820px] -translate-x-1/2 rounded-full opacity-30 blur-3xl"
        style={{
          background: "radial-gradient(closest-side, var(--color-glow), transparent 70%)",
        }}
      />

      <div className="relative mx-auto max-w-7xl px-6 py-16 lg:py-24">
        {/* centered heading */}
        <div className="mx-auto max-w-3xl text-center">
          <span className="inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-3 py-1 text-xs text-muted-foreground backdrop-blur-sm">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" />
            One key for your entire AI stack
          </span>

          <h1 className="mt-6 text-balance text-5xl font-semibold leading-[1.05] tracking-tight md:text-6xl lg:text-7xl">
            The AI Gateway <span className="text-primary text-glow">for platform teams</span>
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-pretty text-lg leading-relaxed text-muted-foreground">
            Put your full AI stack behind one key. See who is driving spend, cap it before it runs,
            and send each request to the model that should handle it — with observability built in.
          </p>

          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Button size="lg" className="gap-2">
              Start free
              <ArrowRight className="h-4 w-4" />
            </Button>
            <Button size="lg" variant="outline">
              Talk to sales
            </Button>
          </div>
          <p className="mt-4 font-mono text-xs text-muted-foreground">Self-host in minutes. No credit card.</p>
        </div>

        {/* full-width lifecycle animation */}
        <div className="mt-16">
          <RequestLifecycle />
        </div>
      </div>
    </section>
  )
}

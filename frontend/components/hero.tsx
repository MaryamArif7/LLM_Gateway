import { Button } from "@/components/ui/button";
import { RequestLifecycle } from "@/components/request-lifecycle";
import { ArrowRight } from "lucide-react";

export function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 grid-fade opacity-[0.06]"
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

      <div className="relative mx-auto max-w-7xl px-6 py-16 lg:py-24">
        <div className="mx-auto max-w-3xl text-center">
          <h1 className="mt-6 text-balance text-5xl font-semibold leading-[1.05] tracking-tight md:text-6xl lg:text-7xl">
            Every request, routed right and{" "}
            <span className="text-primary text-glow">logged fully</span>
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-pretty text-lg leading-relaxed text-muted-foreground">
            Prompts get classified, sent to the best-fit model, cached when
            possible, and rerouted on failure — with token counts, cost, and
            latency logged for every single one.
          </p>

          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Button size="lg" className="gap-2">
              Open the chat
              <ArrowRight className="h-4 w-4" />
            </Button>
            <Button size="lg" variant="outline">
              Check Github
            </Button>
          </div>
        </div>

        <div className="mt-16">
          <RequestLifecycle />
        </div>
      </div>
    </section>
  );
}

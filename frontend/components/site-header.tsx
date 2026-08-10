import { Button } from "@/components/ui/button"
import { ChevronRight, Boxes } from "lucide-react"

const nav = ["Gateway", "Docs", "Models", "Pricing", "Blog"]

export function SiteHeader() {
  return (
    <header>
      <div className="flex items-center justify-center gap-1.5 bg-primary/90 px-4 py-2 text-center text-xs font-medium text-primary-foreground">
        <span className="font-mono">Self-hosted and air-gapped.</span>
        <span className="opacity-90">Read every line on GitHub</span>
        <ChevronRight className="h-3.5 w-3.5" />
      </div>

      <nav className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
        <div className="flex items-center gap-8">
          <a href="#" className="flex items-center gap-2 font-semibold tracking-tight">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Boxes className="h-4 w-4" />
            </span>
            AI Gateway
          </a>
          <ul className="hidden items-center gap-6 text-sm text-muted-foreground md:flex">
            {nav.map((item) => (
              <li key={item}>
                <a href="#" className="transition-colors hover:text-foreground">
                  {item}
                </a>
              </li>
            ))}
          </ul>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="ghost" className="hidden sm:inline-flex">
            Book demo
          </Button>
          <Button>Get started</Button>
        </div>
      </nav>
    </header>
  )
}

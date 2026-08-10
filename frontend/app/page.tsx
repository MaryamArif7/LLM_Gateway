import { SiteHeader } from "@/components/site-header"
import { Hero } from "@/components/hero"

export default function Page() {
  return (
    <main className="min-h-svh bg-background">
      <SiteHeader />
      <Hero />
    </main>
  )
}

import Link from "next/link";
import {
  ShieldCheck,
  Network,
  Gauge,
  Layers,
  RefreshCw,
  LineChart,
  KeyRound,
  Lock,
  Zap,
  CheckCircle2,
  GitBranch,
  MessageSquare,
} from "lucide-react";

import { LandingNav } from "@/components/landing-nav";
import { PixelSwarm } from "@/components/pixel-swarm";
import { Reveal } from "@/components/reveal";
import { CodeTabs } from "@/components/code-tabs";
import { ProviderLogo } from "@/components/provider-logo";
import { Typewriter } from "@/components/typewriter";
import { Badge } from "@/components/ui/badge";
import { API_BASE_URL, PROXY_BASE_URL } from "@/lib/config";
import { PROVIDERS, TIERS, TOTAL_MODELS, TOTAL_PROVIDERS } from "@/lib/catalog";
import { cn, providerLabel } from "@/lib/utils";

const TIER_BADGE: Record<string, string> = {
  low: "keychain-low",
  medium: "keychain-medium",
  high: "keychain-high",
};

const PROMPT_CHIPS = [
  "Route a chat through keychain-high",
  "Point Claude Code at your keychain URL",
  "Fail over when Groq rate-limits",
  "Swap OpenAI base URL in one line",
  "Track usage across every provider",
  "Stream completions from any model",
];

export default function LandingPage() {
  return (
    <div className="relative overflow-x-clip bg-background">
      <LandingNav />
      <Hero />
      <PromptChips />
      <LogoWall />
      <StatsBand />
      <Features />
      <HowItWorks />
      <ModelsByProvider />
      <Tiers />
      <Quickstart />
      <FinalCta />
      <Footer />
    </div>
  );
}

/* ------------------------------------------------------------------ Hero */

function Hero() {
  return (
    <section className="relative overflow-hidden px-5 pt-32 pb-20 sm:px-8 sm:pt-40 sm:pb-24">
      <PixelSwarm className="[mask-image:radial-gradient(ellipse_at_center,black_30%,transparent_80%)]" />
      {/* Dark scrim so the hero copy stays legible over the swarm. */}
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-1/2 h-[34rem] w-[52rem] max-w-[92vw] -translate-x-1/2 -translate-y-1/2 [background:radial-gradient(ellipse_at_center,hsl(var(--background))_18%,hsl(var(--background)/0.85)_42%,transparent_72%)]"
      />
      <div className="relative mx-auto max-w-4xl text-center">
        <Reveal delay={60}>
          <h1 className="display-hero font-heading">
            One API key for every
            <br />
            <span className="whitespace-nowrap">
              free{" "}
              <Typewriter
                className="text-primary"
                words={[
                  "AI model.",
                  "Gemini model.",
                  "Llama model.",
                  "Mistral model.",
                  "DeepSeek model.",
                ]}
              />
            </span>
          </h1>
        </Reveal>

        <Reveal delay={120}>
          <p className="mx-auto mt-6 max-w-xl text-pretty text-base leading-relaxed text-foreground/80 sm:text-lg">
            Unify {TOTAL_PROVIDERS} free-tier inference providers behind one
            gateway. OpenAI Chat Completions for Cursor and SDKs, Anthropic
            Messages for Claude Code — with effort-based routing, automatic
            failover, and usage analytics.
          </p>
        </Reveal>
      </div>

      <Reveal delay={280} className="relative mx-auto mt-14 max-w-2xl">
        <CodeTabs
          samples={[
            {
              id: "py",
              label: "Python",
              file: "app.py",
              code: `from openai import OpenAI

client = OpenAI(
    base_url="${PROXY_BASE_URL}",
    api_key="ak-•••••••••••••••",
)

resp = client.chat.completions.create(
    model="keychain-high",
    messages=[{"role": "user", "content": "Explain quantum tunneling."}],
)
print(resp.choices[0].message.content)`,
            },
            {
              id: "ts",
              label: "TypeScript",
              file: "index.ts",
              code: `import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "${PROXY_BASE_URL}",
  apiKey: "ak-•••••••••••••••",
});

const resp = await client.chat.completions.create({
  model: "keychain-medium",
  messages: [{ role: "user", content: "Draft a launch tweet." }],
});`,
            },
            {
              id: "curl",
              label: "curl",
              file: "request.sh",
              code: `curl ${PROXY_BASE_URL}/chat/completions \\
  -H "Authorization: Bearer ak-•••••••••••••••" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "keychain-low", "messages": [{"role": "user", "content": "Hello!"}]}'`,
            },
          ]}
        />
      </Reveal>
    </section>
  );
}

/* ----------------------------------------------------------- Prompt chips */

function PromptChips() {
  return (
    <section className="border-y border-border px-5 py-14 sm:px-8">
      <div className="mx-auto max-w-6xl">
        <SectionHeading
          eyebrow="What could you build?"
          title="Routing intelligence everywhere you call a model"
          subtitle="Point any OpenAI-compatible client at your keychain URL. Pick an effort tier and let the router handle the rest."
          align="center"
        />
        <div className="mt-8 flex flex-wrap justify-center gap-2 sm:gap-3">
          {PROMPT_CHIPS.map((chip, i) => (
            <Reveal key={chip} delay={i * 40}>
              <span className="prompt-chip">{chip}</span>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------- Logo wall */

function LogoWall() {
  return (
    <section id="providers" className="px-5 py-12 sm:px-8">
      <p className="mb-6 text-center text-sm text-muted-foreground">
        Routing across the best free-tier inference networks
      </p>
      <div className="group overflow-hidden">
        <div className="flex w-max animate-marquee group-hover:[animation-play-state:paused]">
          {[...PROVIDERS, ...PROVIDERS].map((p, i) => (
            <div
              key={`${p.slug}-${i}`}
              className="surface mr-3 flex w-60 shrink-0 items-center gap-3 px-4 py-3"
            >
              <ProviderLogo
                domain={p.domain}
                name={p.name}
                iconUrl={p.iconUrl}
                size={36}
              />
              <div className="min-w-0 leading-tight">
                <div className="font-heading text-sm font-medium">{p.name}</div>
                <div className="truncate font-mono text-[10px] text-muted-foreground">
                  {p.freeModels.length} free models
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------- Stats band */

const STATS = [
  { value: `${TOTAL_PROVIDERS}`, label: "Inference providers" },
  { value: `${TOTAL_MODELS}+`, label: "Free-tier models" },
  { value: "3", label: "Routing tiers" },
  { value: "2", label: "Client protocols" },
];

function StatsBand() {
  return (
    <section className="border-t border-border px-5 py-14 sm:px-8">
      <div className="mx-auto grid max-w-5xl grid-cols-2 gap-3 sm:grid-cols-4">
        {STATS.map((s, i) => (
          <Reveal
            key={s.label}
            delay={i * 60}
            className="surface px-5 py-8 text-center"
          >
            <div className="font-heading text-3xl font-medium tabular-nums sm:text-4xl">
              {s.value}
            </div>
            <div className="mt-1.5 text-sm text-muted-foreground">{s.label}</div>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

/* --------------------------------------------------------------- Features */

const FEATURES = [
  {
    icon: Network,
    title: "Effort-based routing",
    body: "Pick fast, balanced, or best (`keychain-low` / `-medium` / `-high`). The router cascades through free models until one answers.",
  },
  {
    icon: MessageSquare,
    title: "Claude Code ready",
    body: "Native Anthropic Messages API with streaming, tools, and token counting — routed through your free-tier providers.",
  },
  {
    icon: RefreshCw,
    title: "Automatic failover",
    body: "A 429 or outage on one provider transparently rolls to the next.",
  },
  {
    icon: Gauge,
    title: "Rate-limit cooldowns",
    body: "Throttled providers are parked in a cooldown window until they recover.",
  },
  {
    icon: ShieldCheck,
    title: "Encrypted at rest",
    body: "Every upstream provider key is sealed with authenticated encryption.",
  },
  {
    icon: KeyRound,
    title: "Unified keychain key",
    body: "One revealable ak- key fronts everything. Bearer or x-api-key auth.",
  },
  {
    icon: Layers,
    title: "Bring your own models",
    body: "Pin any model id into a tier, then reorder priority to taste.",
  },
  {
    icon: LineChart,
    title: "Usage analytics",
    body: "Per-model, per-provider request counts, token totals, and latency.",
  },
];

function Features() {
  return (
    <section id="features" className="px-5 py-16 sm:px-8 sm:py-20">
      <div className="mx-auto max-w-6xl">
        <SectionHeading
          eyebrow="The platform"
          title="A control plane for free AI inference"
          subtitle="Routing, failover, key management and observability — in one OpenAI-compatible gateway."
        />
        <div className="mt-10 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map((f, i) => {
            const Icon = f.icon;
            return (
              <Reveal
                key={f.title}
                delay={(i % 4) * 70}
                className="surface flex h-full flex-col p-6"
              >
                <Icon className="mb-4 h-5 w-5 text-foreground" strokeWidth={1.6} />
                <h3 className="font-heading text-base font-medium tracking-tight">
                  {f.title}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {f.body}
                </p>
              </Reveal>
            );
          })}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------ How it works */

const STEPS = [
  {
    icon: KeyRound,
    title: "Connect your providers",
    body: "Paste the free-tier keys you already have. They're encrypted the moment they arrive.",
  },
  {
    icon: GitBranch,
    title: "Pick an effort tier",
    body: "Send `keychain-low`, `-medium`, or `-high` as the model — fast, balanced, or best free-tier cascades.",
  },
  {
    icon: Zap,
    title: "Ship — we handle the rest",
    body: "Failover, cooldowns and retries happen server-side. You get a clean OpenAI response.",
  },
];

function HowItWorks() {
  return (
    <section className="px-5 py-16 sm:px-8 sm:py-20">
      <div className="mx-auto max-w-6xl">
        <SectionHeading
          eyebrow="How it works"
          title="From twelve dashboards to one request"
          subtitle="No SDK swaps, no per-provider glue. Point OpenAI or Anthropic clients at your keychain URL."
        />

        <div className="mt-10 grid gap-6 lg:grid-cols-[1.1fr_1fr] lg:items-stretch">
          <div className="flex h-full min-h-0 flex-col gap-3">
            {STEPS.map((s, i) => {
              const Icon = s.icon;
              return (
                <Reveal
                  key={s.title}
                  delay={i * 80}
                  className="surface flex flex-1 gap-4 p-5"
                >
                  <span className="shrink-0 font-heading text-sm font-medium tabular-nums text-muted-foreground">
                    {i + 1}
                  </span>
                  <div className="flex flex-col justify-center">
                    <h3 className="flex items-center gap-2 font-heading text-base font-medium tracking-tight">
                      <Icon className="h-4 w-4 text-muted-foreground" />
                      {s.title}
                    </h3>
                    <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                      {s.body}
                    </p>
                  </div>
                </Reveal>
              );
            })}
          </div>

          <Reveal delay={120} className="flex min-h-0 flex-col">
            <CascadeVisual className="min-h-full flex-1" />
          </Reveal>
        </div>
      </div>
    </section>
  );
}

function CascadeVisual({ className }: { className?: string }) {
  const chain = [
    { model: "gemini-2.5-pro", provider: "gemini", state: "429" },
    { model: "deepseek-r1", provider: "deepseek", state: "cooling" },
    { model: "llama-3.3-70b", provider: "groq", state: "ok" },
  ];
  return (
    <div className={cn("panel flex flex-col p-6", className)}>
      <div className="mb-5 flex shrink-0 items-center justify-between">
        <span className="font-heading text-sm font-medium">keychain-high</span>
        <Badge variant="muted" className="font-mono normal-case">
          effort: high
        </Badge>
      </div>

      <div className="flex flex-1 flex-col justify-center gap-2">
        {chain.map((c, i) => {
          const ok = c.state === "ok";
          return (
            <div
              key={c.model}
              className={cn(
                "flex items-center gap-3 rounded-md border px-3.5 py-2.5",
                ok ? "border-foreground/20 bg-secondary" : "border-border bg-background"
              )}
            >
              <span
                className={cn(
                  "shrink-0 text-[10px] font-medium tabular-nums",
                  ok ? "text-foreground" : "text-muted-foreground"
                )}
              >
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate font-mono text-xs">{c.model}</div>
                <div className="text-[10px] text-muted-foreground">
                  {providerLabel(c.provider)}
                </div>
              </div>
              {c.state === "429" && <Badge variant="danger">429 · skip</Badge>}
              {c.state === "cooling" && (
                <Badge variant="warning">cooling · skip</Badge>
              )}
              {ok && (
                <Badge variant="success">
                  <CheckCircle2 className="h-3 w-3" /> served
                </Badge>
              )}
            </div>
          );
        })}
      </div>

      <div className="mt-5 flex shrink-0 items-center justify-between border-t border-border pt-4 text-xs text-muted-foreground">
        <span>1 request in</span>
        <span className="font-mono">2 skipped · 1 served</span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------ Models by provider */

function ModelsByProvider() {
  return (
    <section id="models" className="border-t border-border px-5 py-16 sm:px-8 sm:py-20">
      <div className="mx-auto max-w-6xl">
        <SectionHeading
          eyebrow="The catalog"
          title="Every free model, one key"
          subtitle={`All ${TOTAL_MODELS} free-tier models across ${TOTAL_PROVIDERS} providers.`}
        />
        <div className="mt-10 grid gap-4 sm:grid-cols-2">
          {PROVIDERS.map((p, i) => (
            <Reveal key={p.slug} delay={(i % 2) * 80} className="min-w-0">
              <div className="surface h-full p-6">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <ProviderLogo
                      domain={p.domain}
                      name={p.name}
                      iconUrl={p.iconUrl}
                      size={40}
                    />
                    <div className="min-w-0">
                      <div className="truncate font-heading text-base font-medium">
                        {p.name}
                      </div>
                      <div className="truncate font-mono text-[10px] text-muted-foreground">
                        {p.baseUrl}
                      </div>
                    </div>
                  </div>
                  <Badge variant="muted" className="shrink-0">
                    {p.freeModels.length} models
                  </Badge>
                </div>
                <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                  {p.tagline}
                </p>
                <div className="mt-4 flex flex-wrap gap-1.5">
                  {p.freeModels.map((m) => (
                    <span
                      key={m}
                      className="rounded-full border border-border bg-secondary px-2.5 py-1 font-mono text-[11px] text-foreground/80"
                    >
                      {m}
                    </span>
                  ))}
                </div>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ Tiers */

function Tiers() {
  return (
    <section id="tiers" className="px-5 py-16 sm:px-8 sm:py-20">
      <div className="mx-auto max-w-6xl">
        <SectionHeading
          eyebrow="Routing tiers"
          title="Fast, balanced, or best — all free"
          subtitle="Tiers trade speed for capability across free models, not price. Reorder, disable, or extend any cascade from your dashboard."
        />
        <div className="mt-10 grid gap-4 lg:grid-cols-3">
          {TIERS.map((t, i) => (
            <Reveal key={t.tier} delay={i * 80} className="h-full min-w-0">
              <div className="surface flex h-full flex-col p-6">
                <div className="flex items-center justify-between gap-2">
                  <span className="min-w-0 truncate font-heading text-lg font-medium capitalize">
                    {t.label}
                  </span>
                  <Badge variant="muted" className="shrink-0 font-mono normal-case">
                    {TIER_BADGE[t.tier]}
                  </Badge>
                </div>
                <p className="mt-2 min-h-[3.5rem] text-sm leading-relaxed text-muted-foreground">
                  {t.blurb}
                </p>
                <div className="mt-4">
                  <div className="mb-2.5 text-xs font-medium text-muted-foreground">
                    Cascade order
                  </div>
                  <ul className="space-y-1.5">
                    {t.models.map((m, idx) => (
                      <li
                        key={m}
                        className="flex min-w-0 items-center gap-2.5 font-mono text-xs text-foreground/80"
                      >
                        <span className="shrink-0 text-[9px] tabular-nums text-muted-foreground">
                          {idx + 1}
                        </span>
                        <span className="min-w-0 truncate">{m}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------- Quickstart */

function Quickstart() {
  return (
    <section id="start" className="border-t border-border px-5 py-16 sm:px-8 sm:py-20">
      <div className="mx-auto grid max-w-6xl gap-10 lg:grid-cols-2 lg:items-center">
        <Reveal>
          <SectionHeading
            align="left"
            eyebrow="Quickstart"
            title="If you can call OpenAI or Claude, you're already done"
            subtitle="Swap the base URL and key. Chat Completions, Responses API, and Anthropic Messages all route through the same cascade."
          />
          <ul className="mt-6 space-y-3">
            {[
              { Icon: Lock, label: "Drop-in base URL & ak- key (Bearer or x-api-key)" },
              { Icon: Network, label: "Server-side routing & failover" },
              { Icon: LineChart, label: "Every call logged for analytics" },
            ].map(({ Icon, label }) => (
              <li key={label} className="flex items-center gap-3 text-sm">
                <Icon className="h-4 w-4 shrink-0 text-foreground" />
                <span className="text-muted-foreground">{label}</span>
              </li>
            ))}
          </ul>
        </Reveal>

        <Reveal delay={120}>
          <CodeTabs
            samples={[
              {
                id: "before",
                label: "Before",
                file: "before.py",
                code: `# A different SDK + key per provider…
from google import genai
from groq import Groq
from mistralai import Mistral

g = genai.Client(api_key=GEMINI_KEY)
q = Groq(api_key=GROQ_KEY)
m = Mistral(api_key=MISTRAL_KEY)
# …and you hand-roll the failover.`,
              },
              {
                id: "claude",
                label: "Claude Code",
                file: "claude.sh",
                code: `export ANTHROPIC_BASE_URL="${API_BASE_URL}"
export ANTHROPIC_API_KEY="ak-•••••••••••••••"

# Claude Code uses /v1/messages — routed via your tier cascade
claude`,
              },
              {
                id: "codex",
                label: "Codex CLI",
                file: "codex.sh",
                code: `export OPENAI_BASE_URL="${PROXY_BASE_URL}"
export OPENAI_API_KEY="ak-•••••••••••••••"

# Codex CLI v0.136+ uses POST /v1/responses
codex`,
              },
              {
                id: "after",
                label: "OpenAI SDK",
                file: "after.py",
                code: `from openai import OpenAI

client = OpenAI(
    base_url="${PROXY_BASE_URL}",
    api_key="ak-•••••••••••••••",
)

resp = client.chat.completions.create(
    model="keychain-medium",
    messages=[{"role": "user", "content": "Summarize this."}],
)`,
              },
            ]}
          />
        </Reveal>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------- Final CTA */

function FinalCta() {
  return (
    <section className="border-t border-border px-5 py-16 sm:px-8 sm:py-20">
      <Reveal className="mx-auto max-w-3xl text-center">
        <h2 className="font-heading text-3xl font-medium leading-tight tracking-tight sm:text-5xl">
          Interested in seeing how API Keychain works for your stack?
        </h2>
        <p className="mx-auto mt-4 max-w-lg text-base text-muted-foreground">
          Spin up your unified key in under a minute and route across every
          free-tier model from a single endpoint.
        </p>
      </Reveal>
    </section>
  );
}

/* ----------------------------------------------------------------- Footer */

function Footer() {
  return (
    <footer className="border-t border-border px-5 py-10 sm:px-8">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 sm:flex-row">
        <div className="flex items-center gap-2.5">
          <span className="font-heading text-sm font-semibold">API Keychain</span>
          <span className="text-xs text-muted-foreground">
            · One key for every AI provider
          </span>
        </div>
      </div>
      <div className="mx-auto mt-4 max-w-6xl text-center text-xs text-muted-foreground sm:text-left">
        © {new Date().getFullYear()} API Keychain. Routes across{" "}
        {PROVIDERS.map((p) => providerLabel(p.slug)).join(", ")}.
      </div>
    </footer>
  );
}

/* --------------------------------------------------------------- Shared */

function SectionHeading({
  eyebrow,
  title,
  subtitle,
  align = "center",
}: {
  eyebrow: string;
  title: string;
  subtitle?: string;
  align?: "center" | "left";
}) {
  return (
    <div className={align === "center" ? "mx-auto max-w-2xl text-center" : "max-w-xl"}>
      <p className="text-sm font-medium text-muted-foreground">{eyebrow}</p>
      <h2 className="mt-2 font-heading text-3xl font-medium leading-tight tracking-tight sm:text-4xl">
        {title}
      </h2>
      {subtitle && (
        <p className="mt-3 text-base leading-relaxed text-muted-foreground">
          {subtitle}
        </p>
      )}
    </div>
  );
}

<div align="center">

<img src="./.github/hero.svg" alt="API Keychain — one key for every free AI model" width="720" />

<br />

<p align="center">
  <img src="https://img.shields.io/badge/Next.js_14-000000?style=flat-square&logo=nextdotjs&logoColor=white" alt="Next.js 14" />
  <img src="https://img.shields.io/badge/React_18-20232A?style=flat-square&logo=react&logoColor=61DAFB" alt="React 18" />
  <img src="https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white" alt="TypeScript" />
  <img src="https://img.shields.io/badge/Tailwind_CSS-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white" alt="Tailwind CSS" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/SQLAlchemy-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white" alt="SQLAlchemy" />
  <img src="https://img.shields.io/badge/Supabase_Auth-3FCF8E?style=flat-square&logo=supabase&logoColor=white" alt="Supabase Auth" />
  <img src="https://img.shields.io/badge/License-MIT-3DA639?style=flat-square" alt="MIT License" />
</p>

<p align="center">
  <b><a href="https://www.apikeychain.dev">Dashboard</a></b>
  &nbsp;·&nbsp;
  <b><a href="https://api.apikeychain.dev/health">Gateway health</a></b>
  &nbsp;·&nbsp;
  <b><a href="docs/getting-started.md">Get started</a></b>
</p>

<p align="center">
  One unified key fronts twelve free-tier inference providers behind the OpenAI
  Chat Completions and Anthropic Messages APIs — with effort-based routing,
  automatic failover, rate-limit cooldowns, encrypted key storage, and full
  usage analytics.
</p>

</div>

## Overview

Modern apps want the generous free tiers from Gemini, Groq, Cerebras, Mistral,
DeepSeek, OpenRouter, Together, Cohere, NVIDIA NIM, SambaNova, Hugging Face, and
Cloudflare Workers AI. In practice that means a different SDK and key for every
provider, hand-rolled failover when one returns a `429`, and no shared view of
what ran where.

API Keychain collapses all of that into one gateway. You send a single keychain
key and ask for an effort tier (`keychain-low`, `keychain-medium`,
`keychain-high`) or a Claude pseudo-model (`claude-haiku-4-5`,
`claude-sonnet-4-6`, `claude-opus-4-6`). The router builds an ordered cascade of
real models, tries them in priority order, skips anything throttled or cooling
down, and returns a clean response. OpenAI clients use `/v1/chat/completions`;
Claude Code uses `/v1/messages` — same routing underneath.

> If your code already calls OpenAI or Claude, the only change is the **base URL**
> and the **key**.

## How routing works

<div align="center">
  <img src="./.github/routing.svg" alt="A keychain-high request cascades through candidate models; a 429 fails over to the next until one returns 200 OK" width="760" />
</div>

A single `keychain-high` request flows through the gateway like this:

1. The router expands the requested tier into an ordered cascade of model
   entries, highest priority first — honoring your enabled models, excluded
   models, and preferred providers.
2. It walks the cascade. Any model whose provider is in a cooldown window, is
   excluded, or has no key is skipped.
3. The first model that returns a successful completion wins. Its response is
   normalized to the OpenAI schema and returned to the caller.
4. If a model returns a `429`, its provider is parked in a cooldown window and
   the router continues to the next candidate.
5. The attempt, serving model and provider, token usage, latency, and status are
   written to the request log that powers the dashboard.

**One request in, automatic failover across providers, one clean response out.**

## Highlights

| Capability | What it does |
| :-- | :-- |
| **Effort-based routing** | Request `low`, `medium`, or `high` (fast, balanced, best). The router cascades through free models until one answers. |
| **Automatic failover** | A `429` or upstream outage transparently rolls to the next model, so the request still completes. |
| **Rate-limit cooldowns** | A just-throttled provider is parked in a cooldown window and skipped until it recovers. |
| **Encrypted at rest** | Every upstream provider key is sealed with AES-256-GCM before it touches the database. |
| **Bring your own models** | Pin any model id a connected provider supports into a tier, then reorder its priority. |
| **Usage analytics** | Per-model and per-provider request counts, token totals, success rate, latency, and daily volume. |
| **Unified keychain key** | One revealable `ak-` key fronts everything and rotates without touching upstream credentials. |
| **OpenAI-compatible** | Drop-in `/v1/chat/completions` and `/v1/models` for OpenAI SDKs (Cursor, OpenCode, etc.). |
| **Anthropic Messages** | Native `/v1/messages` and `/v1/messages/count_tokens` for Claude Code and Anthropic-format clients. |
| **Dual auth** | Bearer token or `x-api-key` header with your `ak-` keychain key. |

## Quickstart

> **Prerequisites** — Node.js 18+, Python 3.10+, and a Supabase project for auth.

### 1 · Backend

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export MASTER_SECRET="a-long-stable-secret"
export SUPABASE_JWT_SECRET="your-supabase-legacy-jwt-secret"
export SUPABASE_URL="https://<project-ref>.supabase.co"

uvicorn main:app --reload
```

The gateway listens on `http://localhost:8000`. Locally, SQLAlchemy defaults to
`keychain.db` in the project root. `MASTER_SECRET` must stay stable once set —
it decrypts the provider keys already in the database. For production
persistence, set `DATABASE_URL` to PostgreSQL — see
[Installation → Database](docs/installation.md#database).

### 2 · Frontend

```sh
npm install
cp .env.example .env.local   # then fill in the values
npm run dev
```

The dashboard runs on `http://localhost:3000` and points at the gateway through
`NEXT_PUBLIC_API_BASE_URL`.

## Using the API

Point any **OpenAI Chat Completions** client at the gateway and select an effort
tier as the model. For **Claude Code**, set `ANTHROPIC_BASE_URL` to your gateway
(without `/v1`) and `ANTHROPIC_API_KEY` to your `ak-` key.

### Python

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="ak-your-keychain-key",
)

resp = client.chat.completions.create(
    model="keychain-high",  # keychain-low | keychain-medium | keychain-high
    messages=[{"role": "user", "content": "Explain quantum tunneling."}],
)
print(resp.choices[0].message.content)
```

### TypeScript

```ts
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://localhost:8000/v1",
  apiKey: "ak-your-keychain-key",
});

const resp = await client.chat.completions.create({
  model: "keychain-medium",
  messages: [{ role: "user", content: "Draft a launch tweet." }],
});
```

### Claude Code

```sh
export ANTHROPIC_BASE_URL="http://localhost:8000"
export ANTHROPIC_API_KEY="ak-your-keychain-key"
```

Claude Code calls `POST /v1/messages`. Model names like `claude-sonnet-4-6` map
to effort tiers (`haiku` → low, `sonnet` → medium, `opus` → high) before routing
through your provider cascade.

### curl

```sh
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer ak-your-keychain-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "keychain-low",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

**Compatibility note** — the gateway implements OpenAI Chat Completions, OpenAI
model listing, and Anthropic Messages. Tools that require other protocols need a
bridge:

| Client | Protocol | Works with Keychain? |
| :-- | :-- | :-- |
| OpenAI SDK, Cursor, OpenCode, curl | Chat Completions (`/v1/chat/completions`) | Yes |
| Claude Code | Anthropic Messages (`/v1/messages`) | Yes |
| OpenAI Codex CLI (2026+) | Responses API (`/v1/responses`) | No — use LiteLLM as a bridge, or Cursor/OpenCode |

## Effort tiers

Each tier is an ordered cascade of real models. Reorder, disable, or extend any
of them from the dashboard.

| Tier | Pseudo-model | Profile | Example models in the cascade |
| :-- | :-- | :-- | :-- |
| **Fast** | `keychain-low` | Smallest, fastest free models | `gemini-2.0-flash`, `nim/meta/llama-3.1-8b-instruct` |
| **Balanced** | `keychain-medium` | Everyday chat and agents | `groq/llama-3.3-70b-versatile`, `mistral-small-latest` |
| **Best** | `keychain-high` | Strongest free models | `gemini-2.5-pro`, `deepseek/deepseek-r1` |

> All tiers use **free-tier** upstream models only — tiers pick speed vs.
> capability, not price.

## Supported providers

| Provider | Endpoint | Notes |
| :-- | :-- | :-- |
| Gemini | `generativelanguage.googleapis.com` | Google multimodal models |
| Groq | `api.groq.com` | LPU inference |
| Cerebras | `api.cerebras.ai` | Wafer-scale speed |
| Mistral | `api.mistral.ai` | European frontier models |
| DeepSeek | `api.deepseek.com` | Reasoning models |
| OpenRouter | `openrouter.ai` | Meta-gateway to community free models |
| Together | `api.together.xyz` | Open-source hosting |
| Cohere | `api.cohere.ai` | Command models |
| NVIDIA NIM | `integrate.api.nvidia.com` | NVIDIA-hosted open models |
| SambaNova | `api.sambanova.ai` | Llama on SambaNova Cloud |
| Hugging Face | `router.huggingface.co` | HF inference router |
| Cloudflare | `api.cloudflare.com` | Workers AI (requires account ID) |

Every provider is OpenAI-compatible upstream, so the gateway forwards a
normalized request and reads back a normalized response.

## Architecture

| Layer | Stack | Responsibility |
| :-- | :-- | :-- |
| **Frontend** | Next.js 14 (App Router), React 18, TypeScript, Tailwind CSS, SWR, Recharts | Marketing landing page, authentication, and the management dashboard. |
| **Auth** | Supabase (email + password) | Issues the JWT used to authorize management endpoints. |
| **Gateway** | FastAPI, httpx | OpenAI-compatible proxy, routing, failover, cooldowns, and logging. |
| **Storage** | SQLAlchemy (SQLite locally, PostgreSQL in production) | Users, keychain keys, encrypted provider keys, model overrides, preferences, health, request logs. |
| **Crypto** | `cryptography` (AES-256-GCM) | Authenticated encryption of provider keys at rest. |

The frontend talks to the gateway over HTTP. Management calls carry the Supabase
JWT; inference calls carry the keychain `ak-` key as a bearer token, exactly as
an OpenAI client would.

<details>
<summary><b>Configuration variables</b></summary>

The frontend reads `NEXT_PUBLIC_` variables at build time. The backend reads its
own variables from the process environment; `env_loader.py` loads `.env.local`
and `.env` from the project root on startup.

| Variable | Scope | Description |
| :-- | :-- | :-- |
| `NEXT_PUBLIC_SUPABASE_URL` | Frontend | Supabase project URL. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Frontend | Supabase anon / publishable key (`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` also works). |
| `NEXT_PUBLIC_API_BASE_URL` | Frontend | Base URL of the gateway, without a trailing slash. |
| `SUPABASE_URL` | Frontend (server) | Same project URL; used by `@supabase/server` on Vercel. |
| `SUPABASE_PUBLISHABLE_KEY` | Frontend (server) | Publishable key for server-side Supabase helpers. |
| `SUPABASE_SECRET_KEY` | Frontend (server) | Service-role key — server only, never `NEXT_PUBLIC_`. |
| `SUPABASE_JWKS_URL` | Frontend (server) | JWKS endpoint for JWT verification (optional if derived from `SUPABASE_URL`). |
| `MASTER_SECRET` | Backend | Encrypts stored provider keys with AES-256-GCM. Keep it stable. |
| `SUPABASE_JWT_SECRET` | Backend | Verifies Supabase JWTs on management endpoints (legacy HS256). |
| `SUPABASE_URL` | Backend | Project URL; used to fetch JWKS for asymmetric JWT verification. |
| `DATABASE_URL` | Backend | **Required on Render.** PostgreSQL connection string (`postgresql+psycopg2://…`). Omit locally to use SQLite. |
| `CORS_ORIGINS` | Backend | Comma-separated browser origins allowed to call the gateway. Defaults include `http://localhost:3000`, `https://www.apikeychain.dev`, `https://apikeychain.dev`. |

Full tables and examples: [Configuration](docs/configuration.md) and [.env.example](.env.example).

</details>

## API reference

Management endpoints are authorized with the Supabase JWT. Gateway endpoints are
authorized with the keychain `ak-` key. Public endpoints need no auth.

| Method | Path | Auth | Description |
| :-- | :-- | :-- | :-- |
| `POST` | `/users/init` | JWT | Idempotently onboard the signed-in user. |
| `GET` `POST` | `/users/{id}/keychain-keys` | JWT | List or mint keychain keys. |
| `POST` | `/users/{id}/regenerate-key` | JWT | Rotate the primary keychain key. |
| `GET` `POST` `DELETE` | `/users/{id}/keys` | JWT | Manage encrypted provider keys. |
| `GET` `PUT` `POST` `DELETE` | `/users/{id}/models` | JWT | Enable, prioritize, and extend models. |
| `GET` `PUT` | `/users/{id}/preferences` | JWT | Preferred and excluded providers and models. |
| `GET` | `/users/{id}/providers/health` | JWT | Per-provider status, cooldowns, and counts. |
| `GET` | `/users/{id}/usage` | JWT | Aggregate usage and breakdowns. |
| `POST` | `/v1/chat/completions` | Keychain key | OpenAI-compatible chat completions. |
| `POST` | `/v1/messages` | Keychain key | Anthropic Messages API (Claude Code). |
| `POST` | `/v1/messages/count_tokens` | Keychain key | Token estimate for Anthropic clients. |
| `GET` | `/v1/models` | Keychain key | OpenAI-compatible model list. |
| `GET` | `/providers` `/models` `/health` | Public | Catalog and service health. |

## Security model

Provider keys are encrypted with AES-256-GCM using `MASTER_SECRET` before they
are stored, and are only decrypted in memory at request time to call upstream.
The dashboard never receives a raw provider key back. The keychain `ak-` key is
shown once on creation and stored masked thereafter, and can be rotated at any
time — which immediately invalidates the previous key. Management endpoints
verify the Supabase JWT (both legacy HS256 and asymmetric signing keys via the
project JWKS), and every gateway request is scoped to the owning user.

## Deployment

| Component | Reference URL |
| :-- | :-- |
| Dashboard | `https://www.apikeychain.dev` |
| Gateway | `https://api.apikeychain.dev` |

- **Dashboard (Vercel)** — standard Next.js deploy. Set `NEXT_PUBLIC_SUPABASE_URL`,
  `NEXT_PUBLIC_SUPABASE_ANON_KEY`, and `NEXT_PUBLIC_API_BASE_URL` (the public
  gateway URL, not `localhost`). Optionally set server-only Supabase vars for
  `@supabase/server` — see [Installation](docs/installation.md).
- **Gateway (Render, Railway, Fly, …)** — run
  `uvicorn main:app --host 0.0.0.0 --port $PORT`. On Render, set
  `PYTHON_VERSION=3.12.8`. Required secrets: `MASTER_SECRET`,
  `SUPABASE_JWT_SECRET`, `SUPABASE_URL`. Set `CORS_ORIGINS` for custom domains.
- **Database (critical on Render)** — Render's filesystem is ephemeral. Without
  `DATABASE_URL`, SQLite is deleted on every deploy. Use Supabase Postgres
  (session pooler URI, `postgresql+psycopg2://…`) or another hosted Postgres.
  Tables are created automatically on startup —
  [Installation → Database](docs/installation.md#database).
- **Supabase auth URLs** — Site URL `https://www.apikeychain.dev`, redirect
  `https://www.apikeychain.dev/auth/callback` (needed for email confirmation and
  password reset). Add `https://apikeychain.dev/**` if the apex domain also
  serves the dashboard.

## Documentation

| Guide | Description |
| :-- | :-- |
| [Getting started](docs/getting-started.md) | First run, keys, and a test completion |
| [Installation](docs/installation.md) | Local dev, Vercel + Render production, Postgres persistence |
| [Configuration](docs/configuration.md) | Env vars, tiers, preferences, and routing knobs |
| [API reference](docs/api-reference.md) | Full endpoint list and request shapes |
| [Architecture](docs/architecture.md) | Components, auth flow, and data model |
| [Troubleshooting](docs/troubleshooting.md) | Common errors (CORS, 401, DB, deploy) |
| [FAQ](docs/faq.md) | Streaming, tiers, keys, and compatibility |
| [Examples](examples/) | curl, Python, TypeScript, Node, and Next.js samples |

See also [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## Project structure

```
api-keychain/
├─ app/                  Next.js App Router: landing, login, dashboard, API routes
├─ components/           UI primitives and feature components
├─ lib/                  API client, auth, Supabase (browser + server), catalog
├─ docs/                 Installation, configuration, API reference, architecture
├─ examples/             Runnable curl, Python, TypeScript, Node, Next.js samples
├─ main.py               FastAPI application, gateway and management API
├─ anthropic_adapter.py  Anthropic ↔ OpenAI translation for /v1/messages
├─ env_loader.py         Loads .env.local / .env before other modules read env
├─ router.py             Request routing, cascade, and failover
├─ registry.py           Provider catalog and model tiers
├─ crypto.py             AES-256-GCM provider-key encryption
├─ models.py             SQLAlchemy models and DB engine (SQLite or Postgres)
└─ middleware.ts         Supabase session refresh for Next.js
```

## License

Released under the [MIT License](LICENSE).

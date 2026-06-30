# Architecture

API Keychain is a two-tier application: a **FastAPI gateway** that proxies and
routes inference requests, and a **Next.js dashboard** for configuration and
analytics.

## High-level diagram

```mermaid
flowchart TB
    subgraph clients [Clients]
        SDK[OpenAI SDK / curl]
        Codex[Codex CLI]
        Claude[Claude Code]
        Browser[Dashboard browser]
    end

    subgraph frontend [Next.js Dashboard :3000]
        Pages[App Router pages]
        Auth[Supabase Auth client]
        APIClient[lib/api.ts]
    end

    subgraph supabase [Supabase]
        SupaAuth[Auth / JWT]
    end

    subgraph gateway [FastAPI Gateway :8000]
        Mgmt["/users/* management API"]
        V1["/v1/chat/completions"]
        Responses["/v1/responses"]
        Anthropic["/v1/messages"]
        Adapter[anthropic_adapter.py]
        ResponsesAdapter[responses_adapter.py]
        Router[router.py cascade]
        Crypto[crypto.py AES-GCM]
        Registry[registry.py tiers]
    end

    subgraph storage [Storage]
        DB[(SQLite / PostgreSQL)]
    end

    subgraph upstream [Upstream providers]
        P1[Gemini]
        P2[Groq]
        P3[Others...]
    end

    SDK -->|Bearer ak-...| V1
    Codex -->|Bearer ak-...| Responses
    Claude -->|x-api-key ak-...| Anthropic
    Browser --> Auth
    Auth --> SupaAuth
    Browser --> APIClient
    APIClient -->|JWT| Mgmt
    V1 --> Router
    Responses --> ResponsesAdapter
    ResponsesAdapter --> Router
    Anthropic --> Adapter
    Adapter --> Router
    Mgmt --> Crypto
    Mgmt --> DB
    Router --> Registry
    Router --> Crypto
    Router --> DB
    Router --> P1
    Router --> P2
    Router --> P3
```

## Request routing flow

```mermaid
sequenceDiagram
    participant C as Client
    participant G as Gateway
    participant R as Router
    participant U as Upstream provider
    participant D as Database

    C->>G: POST /v1/chat/completions (ak- key)
    G->>D: Load user keys, preferences, cooldowns
    G->>R: effective_cascade(effort tier)
    loop Each candidate model
        R->>U: POST /chat/completions
        alt Success 2xx
            U-->>R: Completion JSON
            R-->>G: RouteResult
            G->>D: Log request + update health
            G-->>C: OpenAI-shaped response
        else 429 / 5xx / timeout
            U-->>R: Error
            R->>D: Mark provider cooldown (429)
            Note over R: Try next candidate
        end
    end
```

## Component responsibilities

### Gateway (`main.py`)

- FastAPI application entry point
- JWT auth dependency for `/users/*`
- Keychain key auth (`ak-...`) for `/v1/*` — Bearer header or `x-api-key`
- Request logging, usage aggregation, provider health tracking
- Streaming and non-streaming handlers for OpenAI and Anthropic formats

### Anthropic adapter (`anthropic_adapter.py`)

- Translates Anthropic Messages requests to OpenAI Chat Completions bodies
- Maps OpenAI responses and SSE streams back to Anthropic message format
- Resolves effort from Claude model names (`haiku` / `sonnet` / `opus`) or
  `output_config.effort`

### Router (`router.py`)

- Builds ordered candidate list from effort tier + user overrides
- Round-robin across multiple keys per provider
- Deprioritizes providers in cooldown after HTTP 429
- Returns first successful upstream response or aggregates failures

### Registry (`registry.py`)

- Provider catalog with OpenAI-compatible base URLs
- Default `MODEL_TIERS` for low / medium / high
- `effective_cascade()` merges registry with user model table and preferences

### Crypto (`crypto.py`)

- HKDF-derived AES-256-GCM encryption for provider keys at rest
- SHA-256 hashing for keychain token lookup
- Token masking for dashboard display

### Models (`models.py`)

SQLAlchemy entities:

| Model | Purpose |
| --- | --- |
| `User` | Dashboard user linked to Supabase ID |
| `KeychainKey` | `ak-` inference keys (hashed) |
| `ProviderKey` | Encrypted upstream credentials |
| `UserModel` | Per-user model enable/priority overrides |
| `UserPreference` | Preferred/excluded providers and models |
| `ProviderHealth` | Cooldown and status per provider |
| `RequestLog` | Per-request analytics |

### Dashboard (`app/`, `components/`, `lib/`)

- Supabase email/password authentication
- SWR-backed management API client (`lib/api.ts`)
- Pages: dashboard analytics, providers, keys, models, preferences, settings
- Static catalog mirror (`lib/catalog.ts`) for provider metadata in UI

## Authentication surfaces

```mermaid
flowchart LR
    subgraph inference [Inference]
        AK[ak- keychain key]
        V1["POST /v1/chat/completions"]
        MSG["POST /v1/messages"]
        AK --> V1
        AK --> MSG
    end

    subgraph management [Management]
        JWT[Supabase JWT]
        Users["/users/*"]
        JWT --> Users
    end

    subgraph public [Public]
        Health["GET /health"]
        Catalog["/providers · /models"]
    end
```

## Data flow for provider keys

1. User submits plaintext key in dashboard.
2. Gateway receives key over HTTPS on authenticated management route.
3. `encrypt()` stores ciphertext in `ProviderKey.encrypted_key`.
4. On inference, `decrypt()` runs in memory only for the upstream call.
5. Plaintext is never returned to the client after initial storage.

## Deployment topology

Typical production layout:

```mermaid
flowchart LR
    User --> Vercel[Vercel - Next.js]
    User --> LB[Load balancer / TLS]
    LB --> GW[FastAPI instances]
    GW --> PG[(PostgreSQL)]
    Vercel -->|JWT + public API| GW
    User -->|ak- key| LB
    GW --> Providers[LLM provider APIs]
```

## Extension points

- **Custom models:** `POST /users/{id}/models` adds entries to the user cascade
- **Registry overrides:** `provider_catalog(overrides=...)` supports future per-user base URLs
- **DATABASE_URL:** swap SQLite for PostgreSQL without schema changes

See [api-reference.md](api-reference.md) for endpoint details.

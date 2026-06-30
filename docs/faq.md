# FAQ

Detailed frequently asked questions for API Keychain.

## General

### How is API Keychain different from OpenRouter?

API Keychain is **self-hosted** and uses **your own** upstream provider keys.
Routing, failover, cooldowns, and encryption run on your infrastructure. You
control the cascade and can customize tiers per user.

### How many providers and models are supported?

Twelve providers are integrated: Gemini, Groq, Cerebras, Mistral, DeepSeek,
OpenRouter, Together, Cohere, NVIDIA NIM, SambaNova, Hugging Face, and
Cloudflare Workers AI. The dashboard catalog lists free-tier models per
provider; the default tier cascades use a curated subset defined in
`registry.py`.

### Does API Keychain store prompts?

Request metadata (model, provider, tokens, latency, status) is logged to
`RequestLog` for analytics. Review `main.py` logging behavior for your
compliance requirements before production use.

## Routing & tiers

### What happens when I request `keychain-high`?

The gateway builds a cascade starting with high-tier models, then falls through
medium and low if needed. Within each tier, models are tried in priority order
with user overrides applied.

### How do Claude model names map to tiers?

| Model | Tier | Profile |
| --- | --- | --- |
| `claude-haiku-4-5` | low | **Fast** |
| `claude-sonnet-4-6` | medium | **Balanced** |
| `claude-opus-4-6` | high | **Best** |

The same cascade runs whether you call `/v1/chat/completions`,
`/v1/responses` (Codex CLI), or `/v1/messages` (Claude Code) with
`keychain-medium` or `/v1/messages` with `claude-sonnet-4-6`. All upstream
models are free-tier.

### Can I force a specific model?

Pin models via the **Models** page or management API. Disable models you do not
want in the cascade. Direct upstream model IDs are also accepted if you have a
key for that provider.

### How long do cooldowns last?

60 seconds after an upstream HTTP 429. The provider is deprioritized during
cooldown so other providers are tried first.

### Does failover work across tiers?

Yes. A `keychain-high` request that exhausts high-tier candidates continues
into medium, then low.

## Security

### Who can decrypt my provider keys?

Anyone with `MASTER_SECRET` and database access. Protect both aggressively.

### Are keychain keys hashed?

Yes. Only SHA-256 hashes are stored. Plaintext `ak-` tokens are shown once at
creation.

### Is TLS required?

Strongly recommended in production. Terminate TLS at your reverse proxy or
platform.

## API compatibility

### Which endpoints are supported?

**OpenAI-compatible:**

- `POST /v1/chat/completions` (including `stream: true`)
- `POST /v1/responses` (including `stream: true`, for Codex CLI)
- `GET /v1/models`

**Anthropic-compatible:**

- `POST /v1/messages` (including streaming and tool use)
- `POST /v1/messages/count_tokens`

Embeddings, audio, images, assistants, and the OpenAI Responses API are not
implemented.

### Can I use Claude Code?

Yes. Set `ANTHROPIC_BASE_URL` to your gateway host (e.g.
`https://api.apikeychain.dev`) and `ANTHROPIC_API_KEY` to your `ak-` keychain
key. Claude Code sends `x-api-key`, which the gateway accepts.

### Can I use the official OpenAI Python SDK?

Yes. Set `base_url` to your gateway `/v1` prefix and `api_key` to your `ak-`
key.

## Deployment

### Can I run gateway and dashboard on one server?

Yes for small deployments. Use a reverse proxy to route `/` to Next.js and `/v1`
to FastAPI, or run on separate ports as in local dev.

### SQLite vs PostgreSQL?

SQLite is fine for development and single-instance installs. Use PostgreSQL when
running multiple gateway replicas or needing durable backups.

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) and [ROADMAP.md](../ROADMAP.md).

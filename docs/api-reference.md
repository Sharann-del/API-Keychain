# API reference

Base URL: `http://localhost:8000` (or your deployed gateway).

## Authentication

| Route prefix | Auth header |
| --- | --- |
| `/users/*` | `Authorization: Bearer <supabase-jwt>` |
| `/v1/chat/completions`, `/v1/responses`, `/v1/models` | `Authorization: Bearer ak-<keychain-key>` |
| `/v1/messages`, `/v1/messages/count_tokens` | `Authorization: Bearer ak-...` **or** `x-api-key: ak-...` |
| `/health`, `/providers`, `/models` | None |

## Public endpoints

### `GET /health`

Service health check.

### `GET /providers`

Provider catalog metadata (12 providers).

### `GET /models`

Full model registry including tier assignments.

## Gateway — OpenAI-compatible

### `POST /v1/chat/completions`

OpenAI-compatible chat completions with effort-tier routing.

**Headers:** `Authorization: Bearer ak-...`

**Body (subset):**

```json
{
  "model": "keychain-high",
  "messages": [{"role": "user", "content": "Hello"}],
  "stream": false
}
```

**Effort pseudo-models:**

- `keychain-low`
- `keychain-medium`
- `keychain-high`

**Responses:**

- `200` — OpenAI-shaped completion JSON
- `400` — No provider keys configured
- `409` — No models available after filters
- `429` — Per-key rate limit exceeded
- `502` — All providers failed (`all_providers_failed`)

### `POST /v1/responses`

OpenAI Responses API for Codex CLI and other `/v1/responses` clients. Translates
the request to Chat Completions, routes through the same effort-tier cascade,
and returns a Responses-shaped JSON (or SSE stream when `stream: true`).

**Headers:** `Authorization: Bearer ak-...`

**Body (subset):**

```json
{
  "model": "keychain-medium",
  "input": "Hello",
  "stream": false
}
```

Multi-turn agentic clients may send structured `input` arrays with `message`,
`function_call`, `function_call_output`, and `reasoning` items — these are
converted to Chat Completions `messages` before routing.

**Responses:** Same status codes as Chat Completions; body uses the Responses
API `output` array (`message`, `function_call`, etc.) instead of `choices`.

### `GET /v1/models`

OpenAI-compatible model list including:

- `keychain-low`, `keychain-medium`, `keychain-high`
- `claude-haiku-4-5`, `claude-sonnet-4-6`, `claude-opus-4-6`
- User-enabled effective models (when you have a key for that provider)

## Gateway — Anthropic-compatible

For Claude Code and other Anthropic Messages clients.

### `POST /v1/messages`

Translates the request to OpenAI format, routes through the same effort-tier
cascade, and returns an Anthropic-shaped response.

**Headers:** `Authorization: Bearer ak-...` or `x-api-key: ak-...`

**Body (subset):**

```json
{
  "model": "claude-sonnet-4-6",
  "max_tokens": 1024,
  "messages": [{"role": "user", "content": "Hello"}],
  "stream": false
}
```

**Model → effort mapping:**

| Model | Tier | Profile |
| --- | --- | --- |
| `claude-haiku-4-5` | low | Fast |
| `claude-sonnet-4-6` | medium | Balanced |
| `claude-opus-4-6` | high | Best |
| `keychain-low` / `keychain-medium` / `keychain-high` | direct tier | Fast / balanced / best |

Also honors `output_config.effort` when set to `low`, `medium`, or `high`.

**Streaming:** Set `"stream": true` for Anthropic SSE events (`message_start`,
`content_block_delta`, `message_stop`, etc.).

**Error format:** Anthropic-style `{"type": "error", "error": {...}}` (not
OpenAI's `{"error": {...}}`).

### `POST /v1/messages/count_tokens`

Token estimate for Claude Code budgeting.

**Headers:** Same as `/v1/messages`.

**Response:**

```json
{"input_tokens": 42}
```

## User management

All routes require a valid Supabase JWT. The authenticated user must match
`user_id` in the path.

### `POST /users/init`

Idempotently onboard the signed-in user. Call after first login.

### Keychain keys

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/users/{user_id}/keychain-keys` | List keychain keys (masked) |
| `POST` | `/users/{user_id}/keychain-keys` | Create new `ak-` key |
| `POST` | `/users/{user_id}/regenerate-key` | Rotate primary key |
| `PUT` | `/keychain-keys/{key_id}` | Update label or rate limit |
| `DELETE` | `/keychain-keys/{key_id}` | Revoke a key |

### Provider keys

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/users/{user_id}/keys` | Store encrypted provider key |
| `GET` | `/users/{user_id}/keys` | List stored keys (masked) |
| `DELETE` | `/users/{user_id}/keys/{key_id}` | Remove a provider key |

**Store key body:**

```json
{
  "provider": "groq",
  "api_key": "gsk_...",
  "key_label": "default"
}
```

Supported `provider` values: `gemini`, `groq`, `cerebras`, `mistral`,
`deepseek`, `openrouter`, `together`, `cohere`, `nim`, `sambanova`, `hf`,
`cf`.

### Models

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/users/{user_id}/models` | Effective model table |
| `PUT` | `/users/{user_id}/models/{model_id}` | Enable/disable, set priority |
| `POST` | `/users/{user_id}/models` | Add custom model entry |
| `DELETE` | `/users/{user_id}/models/{model_id}` | Remove override |

### Preferences

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/users/{user_id}/preferences` | Routing preferences |
| `PUT` | `/users/{user_id}/preferences` | Update preferred/excluded lists |

### Analytics

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/users/{user_id}/providers/health` | Per-provider status and cooldowns |
| `GET` | `/users/{user_id}/usage` | Aggregate usage stats |
| `GET` | `/users/{user_id}/usage/recent` | Recent request log entries |

## Error format

OpenAI gateway errors:

```json
{
  "error": {
    "message": "All providers failed",
    "type": "api_error",
    "code": "all_providers_failed"
  }
}
```

Anthropic gateway errors:

```json
{
  "type": "error",
  "error": {
    "type": "api_error",
    "message": "All candidate models were exhausted."
  }
}
```

Failed routing attempts may include `failed_attempts` in OpenAI error payloads
for debugging.

## Interactive docs

When running locally, FastAPI serves:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Examples

See [examples/](../examples/) for curl, Python, TypeScript, and Next.js clients.

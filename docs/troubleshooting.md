# Troubleshooting

## Gateway won't start

### `MASTER_SECRET environment variable is not set`

Export a stable secret before starting:

```sh
export MASTER_SECRET="$(openssl rand -hex 32)"
```

### SQLite readonly database

The default database path handles spaces in directory names. If you see readonly
errors:

- Ensure the project directory is writable
- Or set an explicit `DATABASE_URL` with an absolute path:

```sh
export DATABASE_URL="sqlite:////tmp/keychain.db"
```

## Dashboard issues

### Blank page or auth errors

- Verify `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` in `.env.local`
- Restart `npm run dev` after changing env vars
- Check Supabase dashboard → Authentication → Providers → Email enabled

### API calls fail from browser (CORS)

The gateway accepts browser requests from origins in `CORS_ORIGINS`. Defaults:

- `http://localhost:3000` (local dashboard)
- `https://www.apikeychain.dev` (hosted dashboard)

To allow another origin (e.g. a custom domain), add it to `CORS_ORIGINS` on the
gateway host and redeploy.

### `NEXT_PUBLIC_API_BASE_URL` points to localhost in production

Hosted Vercel builds run in the browser. `NEXT_PUBLIC_API_BASE_URL` must be a
public gateway URL such as `https://api.apikeychain.dev`, not
`http://localhost:8000`.

## Inference errors

### `401 Unauthorized` on `/v1/chat/completions` or `/v1/messages`

- Use the **keychain** `ak-` key, not the Supabase JWT
- Ensure the `Authorization: Bearer` header is present (or `x-api-key` for Anthropic clients)
- **Local vs production:** Keys are stored per gateway database. A key minted on
  `localhost:8000` will not work on `api.apikeychain.dev`. On the production
  dashboard, open **Settings → Regenerate primary key** (or sign out and back in
  after deploying the latest dashboard — it auto-mints a key for the current API).
- Rotate the key if it was revoked

### `400 No provider keys configured`

Add at least one upstream provider key via the dashboard or
`POST /users/{user_id}/keys`.

### `409 No models available`

All models in the cascade were filtered out. Check:

- Provider keys exist for providers in the tier
- Models are not excluded in **Preferences**
- Providers are not all in cooldown (wait 60s after heavy 429s)

### `502 all_providers_failed`

Every upstream candidate failed. Inspect `failed_attempts` in the response:

| Status | Likely cause |
| --- | --- |
| 401 | Invalid upstream API key |
| 429 | Rate limited (provider enters cooldown) |
| 5xx | Provider outage |
| timeout | Model too slow or network issue |

### Wrong model capability

Effort tiers are pseudo-models. Use `keychain-high` for the **best** free
models, `keychain-low` for the **fastest**. Customize the cascade in **Models**.

## Encryption & keys

### Cannot decrypt provider keys after deploy

`MASTER_SECRET` changed between encrypt and decrypt. Restore the original secret
or re-enter provider keys.

### Lost keychain `ak-` key

Rotate via dashboard **Keys** → regenerate. Old key stops working immediately.

## Performance

### Slow first request

Cold start on serverless hosts and SQLite lock contention can add latency. Use
a always-on gateway process and PostgreSQL for concurrent load.

### Streaming stalls

Streaming uses a long-lived connection with connect timeout only. Check proxy
idle timeouts (nginx, cloud load balancers) if streams cut off mid-response.

## Getting more help

1. Check [faq.md](faq.md)
2. Search [GitHub Issues](https://github.com/Sharann-del/API-Keychain/issues)
3. Open a [bug report](https://github.com/Sharann-del/API-Keychain/issues/new?template=bug_report.yml) with logs (redact secrets)

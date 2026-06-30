# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 1.0.x | Yes |
| < 1.0 | No |

## Reporting a vulnerability

API Keychain handles **upstream provider API keys** and issues **keychain
`ak-` bearer tokens** that gate inference. Security reports are taken seriously.

**Please do not open public GitHub issues for vulnerabilities.**

Instead:

1. Open a [GitHub Security Advisory](https://github.com/Sharann-del/API-Keychain/security/advisories/new) (preferred), or
2. Email [sharannmanojkumar@gmail.com](mailto:sharannmanojkumar@gmail.com) privately with a clear description, impact, and reproduction steps.

Include:

- Affected component (gateway, dashboard, crypto, auth)
- Steps to reproduce
- Proof-of-concept if available (redact real keys)
- Suggested fix if you have one

We aim to acknowledge reports within **72 hours** and provide a remediation
timeline within **7 days** for confirmed issues.

## Security model

### Provider keys at rest

Upstream provider keys are encrypted with **AES-256-GCM**. The encryption key
is derived from `MASTER_SECRET` via HKDF-SHA256 (`crypto.py`). Ciphertext
includes a random 12-byte nonce per key.

**Operational requirements:**

- Set `MASTER_SECRET` to a long, random value before first use.
- **Never rotate `MASTER_SECRET`** after keys are stored unless you have a
  migration plan — existing ciphertext becomes undecryptable.
- Restrict filesystem and backup access to the SQLite database (`keychain.db`
  by default) or your `DATABASE_URL` backend.

### Keychain keys (`ak-...`)

Keychain keys are high-entropy secrets shown **once** at creation. Only a
SHA-256 hash is stored for lookup. Rotate compromised keys via the dashboard
or `POST /users/{id}/regenerate-key`.

### Authentication

| Surface | Auth mechanism |
| --- | --- |
| `/users/*` management routes | Supabase JWT (HS256 legacy secret and asymmetric JWKS via `SUPABASE_URL`) |
| `/v1/chat/completions`, `/v1/responses`, `/v1/models` | Bearer `ak-...` keychain key |
| `/health`, `/providers`, `/models` | Public catalog endpoints |

### Runtime exposure

Provider keys are decrypted **only in memory** at request time to call upstream
APIs. The dashboard never receives decrypted provider keys back from the API.

### Rate limiting & cooldowns

Per-key rate limits and per-provider cooldown windows (after HTTP 429) reduce
abuse and upstream hammering. These are not a substitute for network-level
controls in production.

## Deployment hardening

When running API Keychain in production:

- Terminate TLS at your reverse proxy or platform load balancer.
- Run the gateway behind a firewall; expose only required ports.
- Use a managed database with encryption at rest for `DATABASE_URL` instead of
  a world-readable SQLite file when possible.
- CORS is set via `CORS_ORIGINS` on the gateway. Defaults include
  `http://localhost:3000`, `https://www.apikeychain.dev`, and `https://apikeychain.dev`.
- Store `MASTER_SECRET`, `SUPABASE_JWT_SECRET`, and Supabase service credentials
  in a secrets manager — not in git or client-side env.
- Never commit `.env.local`, `keychain.db`, or provider keys.

## Disclosure policy

- Confirmed issues are patched on `main` and released with a CHANGELOG entry.
- Credit is given to reporters unless they request anonymity.
- Coordinated disclosure is preferred; we will agree on a publication date with
  the reporter.

## Out of scope

The following are generally **not** accepted as vulnerabilities in this project:

- Missing rate limits on a self-hosted instance you control
- Upstream provider outages or quota exhaustion on free tiers
- Social engineering of dashboard users
- Issues requiring physical access to an already-compromised server

Thank you for helping keep API Keychain and its users' keys safe.

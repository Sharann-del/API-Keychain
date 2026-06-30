# Roadmap

This roadmap reflects the current direction of API Keychain. Timelines are
approximate and priorities may shift based on community feedback.

## Now (v1.0.x) — Stable gateway & dashboard

- [x] OpenAI-compatible `/v1/chat/completions`, `/v1/responses`, and `/v1/models`
- [x] Anthropic-compatible `/v1/messages` for Claude Code
- [x] Effort tiers with cascade failover (`keychain-low` / `medium` / `high`)
- [x] Twelve provider integrations with cooldown-aware routing
- [x] Encrypted provider key storage and keychain key rotation
- [x] Usage analytics and provider health in the dashboard
- [x] Streaming responses (OpenAI Chat Completions, Responses API, and Anthropic SSE)
- [x] Automated test suite for routing and adapter primitives
- [x] GitHub Actions CI on every PR (lint + build + gateway smoke test)
- [x] Configurable CORS origins via `CORS_ORIGINS` environment variable

## Next (v1.1) — Operations & developer experience

- [ ] PostgreSQL-first deployment guide and connection pooling notes
- [ ] Webhook or event hook on routing failures for observability
- [ ] OpenAPI export and published SDK examples in `examples/`
- [ ] Per-model latency and cost attribution in usage API
- [ ] Dashboard: export usage CSV and filter by date range

## Later (v1.2+) — Scale & enterprise patterns

- [ ] Multi-tenant orgs and role-based dashboard access
- [ ] Audit log for key creation, rotation, and provider key changes
- [ ] Pluggable storage backends (S3-compatible export for request logs)
- [ ] Custom provider base URL overrides per user (registry groundwork exists)
- [ ] Helm chart and Docker Compose production profile
- [ ] Optional Redis-backed cooldown state for multi-instance gateways

## Under consideration

- Local Ollama bridge
- Budget caps per keychain key (token or request quotas)
- A/B routing weights within a tier
- CLI (`keychain`) for key management without the dashboard

## How to influence the roadmap

- Open a [feature request](.github/ISSUE_TEMPLATE/feature_request.yml).
- Comment on [GitHub Discussions](https://github.com/Sharann-del/API-Keychain/discussions).
- Submit a PR for documentation or examples — see [CONTRIBUTING.md](CONTRIBUTING.md).

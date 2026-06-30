"""Routing + fallback logic across free-tier LLM providers.

Given a user's available provider keys and a requested effort tier, build a
flattened candidate list that cascades from the requested tier down through the
lower tiers (high -> medium -> low), keeping only models the user has a key for.
Each candidate's provider is called at its OpenAI-compatible
``/chat/completions`` endpoint, in order. On *any* failure — 429, 5xx, 4xx,
timeout, or connection error — we move on to the next candidate. The first 2xx
response wins; an error is only returned to the caller once every candidate
across all reachable tiers has been exhausted.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from crypto import decrypt
from registry import PROVIDER_BASE_URLS, parse_model

# How long to wait on any single upstream before treating it as a failure.
_REQUEST_TIMEOUT = httpx.Timeout(60.0, connect=10.0)

# Streaming responses are long-lived, so there's no overall read timeout — only
# a bound on establishing the connection.
_STREAM_TIMEOUT = httpx.Timeout(None, connect=10.0)

# After a provider returns 429, deprioritize it (try it last) for this window
# rather than hammering it first on every subsequent request.
COOLDOWN_SECONDS = 60

# In-process round-robin cursors, keyed by "<rotation_id>:<provider>". Advancing
# per call spreads load across a provider's multiple keys on successive requests.
_rr_cursor: Dict[str, int] = {}


def _rotate_keys(
    keys: List[tuple[str, str]], rotation_key: str
) -> List[tuple[str, str]]:
    """Return ``keys`` rotated by a per-rotation_key round-robin cursor."""
    if len(keys) <= 1:
        return list(keys)
    idx = _rr_cursor.get(rotation_key, 0) % len(keys)
    _rr_cursor[rotation_key] = idx + 1
    return keys[idx:] + keys[:idx]


@dataclass
class Attempt:
    """Record of one provider call, for diagnostics and usage logging."""

    model_entry: str
    provider: str
    status: Optional[int]
    error: Optional[str]
    key_label: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model_entry,
            "provider": self.provider,
            "status": self.status,
            "error": self.error,
            "key_label": self.key_label,
        }


@dataclass
class RouteResult:
    """A successful route: the upstream JSON plus a trace for logging."""

    data: Dict[str, Any]
    provider: str
    model_entry: str
    upstream_model: str
    # Every attempt made, including the final successful one (status 200).
    attempts: List[Attempt]

    @property
    def usage(self) -> Dict[str, Any]:
        return self.data.get("usage") or {}


class NoModelsAvailable(Exception):
    """User has no key for any model in the requested tier."""


class AllProvidersFailed(Exception):
    """Every candidate model failed (rate limited, errored, or unreachable)."""

    def __init__(self, attempts: List[Attempt]):
        self.attempts = attempts
        summary = "; ".join(
            f"{a.model_entry} -> {a.status or 'ERR'}"
            f"{(' ' + a.error) if a.error else ''}"
            for a in attempts
        )
        super().__init__(f"All providers failed: {summary}")


def _candidate_models(
    models: List[str],
    available_providers: set[str],
    deprioritized_providers: Optional[set[str]] = None,
) -> List[tuple[str, str, str]]:
    """Resolve an ordered model_entry list into routable candidate triples.

    ``models`` is the user's already-ordered effective list (cascade + overrides
    + preferences applied upstream). Here we keep only models whose provider the
    user has a key for, and move ``deprioritized_providers`` (e.g. recently 429'd)
    to the end — still tried as a last resort, just not first. The reorder is
    stable, so relative order within each group is preserved.
    """
    deprioritized = deprioritized_providers or set()
    preferred: List[tuple[str, str, str]] = []
    deferred: List[tuple[str, str, str]] = []
    for entry in models:
        provider, upstream_model = parse_model(entry)
        if provider not in available_providers:
            continue
        triple = (entry, provider, upstream_model)
        (deferred if provider in deprioritized else preferred).append(triple)
    return preferred + deferred


def _build_payload(body: Dict[str, Any], upstream_model: str) -> Dict[str, Any]:
    """Forward an OpenAI-style body, swapping in the upstream model name.

    The custom ``effort`` field is stripped — it's ours, not the provider's.
    A client-supplied ``model`` is ignored in favor of the routed model.
    """
    payload = {k: v for k, v in body.items() if k not in ("effort", "model")}
    payload["model"] = upstream_model
    return payload


async def route_chat_completion(
    *,
    models: List[str],
    body: Dict[str, Any],
    provider_keys: Dict[str, List[tuple[str, str]]],
    deprioritized_providers: Optional[set[str]] = None,
    rotation_id: str = "",
    effort: str = "",
) -> RouteResult:
    """Try the user's effective model list in order; return the first success.

    ``models`` is the ordered effective model_entry list (cascade + per-user
    overrides + preferences already applied). ``provider_keys`` maps provider
    name -> a list of ``(key_label, encrypted_key)`` tuples. When a provider has
    multiple keys they're rotated round-robin across requests, and on a per-request
    failure (429 or otherwise) we try the next key for that same provider before
    moving to the next candidate model.

    The first 2xx wins. Providers in ``deprioritized_providers`` (recently
    rate-limited) are tried last. If every candidate fails, raises
    :class:`AllProvidersFailed`. The returned :class:`RouteResult` carries a full
    attempt trace for usage logging. ``effort`` is annotation-only.
    """
    candidates = _candidate_models(
        models, set(provider_keys.keys()), deprioritized_providers
    )
    if not candidates:
        raise NoModelsAvailable(
            "No enabled model matches your configured providers and preferences. "
            "Add a provider key, enable a model, or relax your exclusions."
        )

    attempts: List[Attempt] = []

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        for model_entry, provider, upstream_model in candidates:
            base_url = PROVIDER_BASE_URLS[provider]
            payload = _build_payload(body, upstream_model)
            keys = _rotate_keys(provider_keys[provider], f"{rotation_id}:{provider}")

            for key_label, encrypted_key in keys:
                api_key = decrypt(encrypted_key)
                try:
                    resp = await client.post(
                        f"{base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                except httpx.RequestError as exc:
                    # Network/connection failure -> try the next key, then the
                    # next candidate.
                    attempts.append(
                        Attempt(model_entry, provider, None, str(exc), key_label)
                    )
                    continue

                if resp.status_code >= 400:
                    # ANY error (429 rate limit, 5xx, or 4xx) fails over: first to
                    # the next key for this provider, then to the next candidate.
                    # We never stop early — a different key/provider may succeed.
                    attempts.append(
                        Attempt(
                            model_entry,
                            provider,
                            resp.status_code,
                            resp.text[:200],
                            key_label,
                        )
                    )
                    continue

                data = resp.json()
                attempts.append(
                    Attempt(model_entry, provider, resp.status_code, None, key_label)
                )
                return RouteResult(
                    data=data,
                    provider=provider,
                    model_entry=model_entry,
                    upstream_model=upstream_model,
                    attempts=attempts,
                )

    raise AllProvidersFailed(attempts)


# --------------------------------------------------------------------------- #
# Streaming (Server-Sent Events) proxy
# --------------------------------------------------------------------------- #
@dataclass
class StreamHandle:
    """A live, already-started upstream stream plus the trace that reached it.

    Holds the open httpx client + response; :func:`iter_stream` drains and closes
    them. Failover happens *before* a handle exists — once one is returned, the
    bytes are committed and there is no falling back.
    """

    client: httpx.AsyncClient
    response: httpx.Response
    provider: str
    model_entry: str
    upstream_model: str
    key_label: Optional[str]
    attempts: List[Attempt]


async def open_stream(
    *,
    models: List[str],
    body: Dict[str, Any],
    provider_keys: Dict[str, List[tuple[str, str]]],
    deprioritized_providers: Optional[set[str]] = None,
    rotation_id: str = "",
) -> StreamHandle:
    """Establish the first upstream stream that *starts* successfully.

    Same candidate/key cascade as :func:`route_chat_completion`, but using a
    streaming request. A candidate that errors *before* the stream begins (non-2xx
    status, connection error) fails over to the next key/model. The first 2xx
    response is returned as a :class:`StreamHandle` with the client/response left
    open for the caller to drain. If none start, raises :class:`AllProvidersFailed`.
    """
    candidates = _candidate_models(
        models, set(provider_keys.keys()), deprioritized_providers
    )
    if not candidates:
        raise NoModelsAvailable(
            "No enabled model matches your configured providers and preferences. "
            "Add a provider key, enable a model, or relax your exclusions."
        )

    attempts: List[Attempt] = []
    client = httpx.AsyncClient(timeout=_STREAM_TIMEOUT)
    try:
        for model_entry, provider, upstream_model in candidates:
            base_url = PROVIDER_BASE_URLS[provider]
            keys = _rotate_keys(provider_keys[provider], f"{rotation_id}:{provider}")

            for key_label, encrypted_key in keys:
                api_key = decrypt(encrypted_key)
                base_payload = _build_payload(body, upstream_model)
                base_payload["stream"] = True
                # Prefer usage in-stream when supported; retry without
                # stream_options on 4xx before failing over to the next key.
                stream_payloads = [
                    {**base_payload, "stream_options": {"include_usage": True}},
                    base_payload,
                ]

                for variant_idx, payload in enumerate(stream_payloads):
                    req = client.build_request(
                        "POST",
                        f"{base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    try:
                        resp = await client.send(req, stream=True)
                    except httpx.RequestError as exc:
                        attempts.append(
                            Attempt(model_entry, provider, None, str(exc), key_label)
                        )
                        break

                    if resp.status_code >= 400:
                        # Error before any stream data -> safe to fail over. Drain the
                        # short error body so the connection can be reused/closed.
                        text = (await resp.aread()).decode("utf-8", "replace")[:200]
                        await resp.aclose()
                        attempts.append(
                            Attempt(
                                model_entry, provider, resp.status_code, text, key_label
                            )
                        )
                        if variant_idx < len(stream_payloads) - 1:
                            continue
                        break

                    attempts.append(
                        Attempt(model_entry, provider, resp.status_code, None, key_label)
                    )
                    return StreamHandle(
                        client=client,
                        response=resp,
                        provider=provider,
                        model_entry=model_entry,
                        upstream_model=upstream_model,
                        key_label=key_label,
                        attempts=attempts,
                    )

        # No candidate started streaming.
        await client.aclose()
        raise AllProvidersFailed(attempts)
    except BaseException:
        # On any error (incl. the AllProvidersFailed above), don't leak the client.
        await client.aclose()
        raise


def _attempts_for_sse(
    attempts: List[Attempt], served_provider: str, served_model: str
) -> List[Dict[str, Any]]:
    """Shape attempt trace for the playground routing SSE event."""
    served_idx: Optional[int] = None
    for i, attempt in enumerate(attempts):
        if (
            attempt.provider == served_provider
            and attempt.model_entry == served_model
            and attempt.status is not None
            and attempt.status < 400
        ):
            served_idx = i
            break

    rows: List[Dict[str, Any]] = []
    for i, attempt in enumerate(attempts):
        rows.append(
            {
                "provider": attempt.provider,
                "model": attempt.model_entry,
                "status": "served" if i == served_idx else "error",
                "code": attempt.status,
            }
        )
    return rows


def _accumulate_usage_from_sse(text: str, usage: Dict[str, Any]) -> None:
    """Merge ``usage`` from OpenAI-style ``data: {...}`` SSE lines (last wins)."""
    for line in text.split("\n"):
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        chunk_usage = data.get("usage")
        if isinstance(chunk_usage, dict) and chunk_usage:
            usage.update(chunk_usage)


async def iter_stream(
    handle: StreamHandle,
    *,
    tier: str = "",
    usage_out: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[bytes]:
    """Yield routing metadata, upstream SSE bytes, then a done event.

    NOTE: if the upstream drops mid-stream, the error surfaces here — there is no
    fallback once streaming has begun (the client already has partial data).
    """
    routing = {
        "tier": tier,
        "attempted": _attempts_for_sse(
            handle.attempts, handle.provider, handle.model_entry
        ),
        "served": {"provider": handle.provider, "model": handle.model_entry},
    }
    yield f"event: routing\ndata: {json.dumps(routing)}\n\n".encode()

    stream_started = time.perf_counter()
    try:
        async for chunk in handle.response.aiter_bytes():
            if usage_out is not None:
                _accumulate_usage_from_sse(
                    chunk.decode("utf-8", errors="replace"), usage_out
                )
            yield chunk
    finally:
        await handle.response.aclose()
        await handle.client.aclose()

    done = {"latency_ms": int((time.perf_counter() - stream_started) * 1000)}
    yield f"event: done\ndata: {json.dumps(done)}\n\n".encode()

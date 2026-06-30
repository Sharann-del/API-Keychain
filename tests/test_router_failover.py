"""Router failover: only exhaust after every candidate/key is tried."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from crypto import encrypt
from router import AllProvidersFailed, open_stream, route_chat_completion


def _encrypted_key() -> str:
    return encrypt("sk-test-key")


@pytest.mark.asyncio
async def test_route_chat_completion_fails_over_to_second_provider():
    provider_keys = {
        "groq": [("main", _encrypted_key())],
        "cerebras": [("main", _encrypted_key())],
    }
    models = ["groq/llama-3.1-8b-instant", "cerebras/llama3.1-8b"]
    call_count = 0

    async def mock_post(url, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        if call_count == 1:
            resp.status_code = 429
            resp.text = "rate limited"
        else:
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {},
            }
        return resp

    with patch("router.httpx.AsyncClient") as mock_client_cls:
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None
        client.post = mock_post
        mock_client_cls.return_value = client

        result = await route_chat_completion(
            models=models,
            body={"messages": [{"role": "user", "content": "hi"}]},
            provider_keys=provider_keys,
        )

    assert result.provider == "cerebras"
    assert len(result.attempts) == 2
    assert result.attempts[0].status == 429
    assert result.attempts[1].status == 200


@pytest.mark.asyncio
async def test_route_chat_completion_502_only_after_all_providers_fail():
    provider_keys = {
        "groq": [("main", _encrypted_key())],
        "cerebras": [("main", _encrypted_key())],
    }
    models = ["groq/llama-3.1-8b-instant", "cerebras/llama3.1-8b"]

    async def mock_post(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 503
        resp.text = "unavailable"
        return resp

    with patch("router.httpx.AsyncClient") as mock_client_cls:
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None
        client.post = mock_post
        mock_client_cls.return_value = client

        with pytest.raises(AllProvidersFailed) as exc_info:
            await route_chat_completion(
                models=models,
                body={"messages": [{"role": "user", "content": "hi"}]},
                provider_keys=provider_keys,
            )

    assert len(exc_info.value.attempts) == 2
    assert {a.provider for a in exc_info.value.attempts} == {"groq", "cerebras"}


@pytest.mark.asyncio
async def test_open_stream_retries_without_stream_options_before_failover():
    provider_keys = {"groq": [("main", _encrypted_key())]}
    models = ["groq/llama-3.1-8b-instant"]
    payloads_seen: list[dict] = []
    send_count = 0

    def mock_build_request(method, url, headers=None, json=None, **kwargs):
        payloads_seen.append(json)
        return httpx.Request(method, url, headers=headers, json=json)

    async def mock_send(req, stream=False):
        nonlocal send_count
        send_count += 1
        resp = MagicMock()
        if send_count == 1:
            resp.status_code = 400
            resp.aread = AsyncMock(return_value=b"stream_options unsupported")
            resp.aclose = AsyncMock()
            return resp
        resp.status_code = 200
        resp.aiter_bytes = MagicMock(return_value=_async_iter([b"data: {}\n\n"]))
        resp.aclose = AsyncMock()
        return resp

    with patch("router.httpx.AsyncClient") as mock_client_cls:
        client = AsyncMock()
        client.build_request = mock_build_request
        client.send = mock_send
        client.aclose = AsyncMock()
        mock_client_cls.return_value = client

        handle = await open_stream(
            models=models,
            body={"messages": [{"role": "user", "content": "hi"}]},
            provider_keys=provider_keys,
        )

    assert handle.provider == "groq"
    assert len(payloads_seen) == 2
    assert "stream_options" in payloads_seen[0]
    assert "stream_options" not in payloads_seen[1]
    assert len(handle.attempts) == 2
    assert handle.attempts[0].status == 400
    assert handle.attempts[1].status == 200


@pytest.mark.asyncio
async def test_open_stream_fails_over_to_second_provider():
    provider_keys = {
        "groq": [("main", _encrypted_key())],
        "cerebras": [("main", _encrypted_key())],
    }
    models = ["groq/llama-3.1-8b-instant", "cerebras/llama3.1-8b"]
    call_count = 0

    async def mock_send(req, stream=False):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        if call_count <= 2:
            resp.status_code = 429
            resp.aread = AsyncMock(return_value=b"rate limited")
            resp.aclose = AsyncMock()
            return resp
        resp.status_code = 200
        resp.aiter_bytes = MagicMock(return_value=_async_iter([b"data: {}\n\n"]))
        resp.aclose = AsyncMock()
        return resp

    with patch("router.httpx.AsyncClient") as mock_client_cls:
        client = AsyncMock()

        def mock_build_request(method, url, headers=None, json=None, **kwargs):
            return httpx.Request(method, url, headers=headers, json=json)

        client.build_request = mock_build_request
        client.send = mock_send
        client.aclose = AsyncMock()
        mock_client_cls.return_value = client

        handle = await open_stream(
            models=models,
            body={"messages": [{"role": "user", "content": "hi"}]},
            provider_keys=provider_keys,
        )

    assert handle.provider == "cerebras"
    assert call_count == 3
    assert any(a.provider == "groq" and a.status == 429 for a in handle.attempts)
    assert any(a.provider == "cerebras" and a.status == 200 for a in handle.attempts)


async def _async_iter(items):
    for item in items:
        yield item

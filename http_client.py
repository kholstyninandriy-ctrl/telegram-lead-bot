"""Спільний async HTTP-клієнт (httpx) — один пул з'єднань на весь бот."""

from __future__ import annotations

import httpx

_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            follow_redirects=True,
            limits=httpx.Limits(max_connections=40, max_keepalive_connections=20),
            headers={"User-Agent": "Mozilla/5.0 (compatible; LeadFinderBot/2.0)"},
        )
    return _client


async def aclose() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None

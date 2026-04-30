"""
Twitter/X source scraper.

Fetches public profile pages and timeline via StealthClient.
Returns raw HTML; parsing is the extractor's responsibility.

Twitter aggressively rate-limits and JS-gates content.  We target the
mobile subdomain (mobile.twitter.com / x.com) which is lighter and
renders more content in the initial HTML payload.
"""
from __future__ import annotations

import logging

from scraper.playwright_client import StealthClient

logger = logging.getLogger(__name__)

# Mobile Twitter tends to return more SSR content
_BASE = "https://mobile.x.com"

_BLOCK_MARKERS = [
    "Something went wrong",
    "This page doesn't exist",
    "account has been suspended",
    "Try again",
]


class TwitterScraper:
    def __init__(self, client: StealthClient) -> None:
        self._client = client

    async def fetch(self, url: str) -> str:
        """
        Fetch a Twitter/X profile URL.
        Rewrites twitter.com → mobile.x.com for lighter rendering.
        """
        mobile_url = _to_mobile(url)
        html = await self._client.fetch(
            mobile_url, wait_until="networkidle", timeout_ms=40_000
        )
        _check_blocked(html, mobile_url)
        return html

    async def fetch_timeline(self, username: str) -> str:
        """Fetch the public timeline page for `username`."""
        url = f"{_BASE}/{username.lstrip('@')}"
        html = await self._client.fetch(
            url, wait_until="networkidle", timeout_ms=40_000
        )
        _check_blocked(html, url)
        return html


def _to_mobile(url: str) -> str:
    for old in ("https://twitter.com", "https://www.twitter.com", "https://x.com", "https://www.x.com"):
        if url.startswith(old):
            return _BASE + url[len(old):]
    return url


def _check_blocked(html: str, url: str) -> None:
    for marker in _BLOCK_MARKERS:
        if marker in html:
            raise TwitterBlockError(f"Blocked/unavailable at {url}: {marker!r}")


class TwitterBlockError(RuntimeError):
    pass

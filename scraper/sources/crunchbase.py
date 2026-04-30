"""
Crunchbase source scraper.

Crunchbase does not offer a free public API for structured data, so we
scrape the public web pages via StealthClient.  The extractor is
responsible for all parsing.

Target URL patterns:
  Organization:  https://www.crunchbase.com/organization/<slug>
  Person:        https://www.crunchbase.com/person/<slug>
"""
from __future__ import annotations

import logging

from scraper.playwright_client import StealthClient

logger = logging.getLogger(__name__)

_BLOCK_MARKERS = [
    "Access denied",
    "cf-browser-verification",
    "Checking your browser",
    "Enable JavaScript",
    "recaptcha",
]
_NOT_FOUND_MARKERS = [
    "Page not found",
    "404",
    "doesn't exist",
]


class CrunchbaseScraper:
    def __init__(self, client: StealthClient) -> None:
        self._client = client

    async def fetch(self, url: str) -> str:
        """
        Fetch a Crunchbase organization or person page.
        Raises `CrunchbaseBlockedError` if bot-detection fires.
        Raises `CrunchbaseNotFoundError` for 404s.
        """
        html = await self._client.fetch(
            url,
            wait_until="networkidle",
            timeout_ms=50_000,
        )
        _check_response(html, url)
        return html

    async def fetch_organization(self, slug: str) -> str:
        url = f"https://www.crunchbase.com/organization/{slug}"
        return await self.fetch(url)

    async def fetch_person(self, slug: str) -> str:
        url = f"https://www.crunchbase.com/person/{slug}"
        return await self.fetch(url)


def _check_response(html: str, url: str) -> None:
    lower = html.lower()
    for marker in _BLOCK_MARKERS:
        if marker.lower() in lower:
            raise CrunchbaseBlockedError(f"Bot detection at {url}: {marker!r}")
    for marker in _NOT_FOUND_MARKERS:
        if marker.lower() in lower:
            raise CrunchbaseNotFoundError(f"Not found at {url}")


class CrunchbaseBlockedError(RuntimeError):
    pass


class CrunchbaseNotFoundError(RuntimeError):
    pass

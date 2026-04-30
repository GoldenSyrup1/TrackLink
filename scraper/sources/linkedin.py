"""
LinkedIn source scraper.

Fetches public profile pages via StealthClient.
Does NOT parse — raw HTML is returned for the extractor.

Detects common anti-bot responses and raises so the scheduler
can mark the job for retry.
"""
from __future__ import annotations

import logging
import re

from scraper.playwright_client import StealthClient

logger = logging.getLogger(__name__)

_AUTHWALL_MARKERS = [
    "authwall",
    "join-now",
    "login",
    "uas/authenticate",
    "Sign in",
]
_CAPTCHA_MARKERS = [
    "challenge",
    "captcha",
    "bot-detection",
]


class LinkedInScraper:
    def __init__(self, client: StealthClient) -> None:
        self._client = client

    async def fetch(self, url: str) -> str:
        """
        Fetch a LinkedIn profile or company page.
        Raises `AuthWallError` or `CaptchaError` if blocked.
        Returns raw HTML otherwise.
        """
        html = await self._client.fetch(url, wait_until="networkidle", timeout_ms=45_000)
        _check_blocked(html, url)
        return html

    async def fetch_posts(self, profile_url: str) -> str:
        """Fetch the 'Recent Activity' page for a profile."""
        activity_url = profile_url.rstrip("/") + "/recent-activity/all/"
        html = await self._client.fetch(
            activity_url, wait_until="networkidle", timeout_ms=45_000
        )
        _check_blocked(html, activity_url)
        return html


def _check_blocked(html: str, url: str) -> None:
    lower = html.lower()
    for marker in _CAPTCHA_MARKERS:
        if marker in lower:
            raise CaptchaError(f"CAPTCHA detected at {url}")
    for marker in _AUTHWALL_MARKERS:
        if marker in lower:
            raise AuthWallError(f"Auth wall detected at {url}")


class AuthWallError(RuntimeError):
    pass


class CaptchaError(RuntimeError):
    pass

"""
GitHub source scraper.

Uses the public GitHub REST API (no auth required for public data).
Returns JSON strings so the extractor can deserialise directly.

Rate limit: 60 req/hr unauthenticated.  Set GITHUB_TOKEN env var to
raise this to 5000/hr; the token is read from settings if present.
"""
from __future__ import annotations

import json
import logging

import httpx

from shared.config import settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.github.com"
_ACCEPT = "application/vnd.github+json"


def _headers() -> dict[str, str]:
    h = {"Accept": _ACCEPT, "X-GitHub-Api-Version": "2022-11-28"}
    token = getattr(settings, "github_token", "")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


class GitHubScraper:
    """
    Fetches GitHub user and repository data via REST API.
    Does NOT use StealthClient — GitHub API is public and rate-limited
    by IP, not bot-detection.
    """

    async def fetch(self, url: str) -> str:
        """
        `url` can be:
          - A full GitHub profile URL: https://github.com/username
          - A GitHub API URL: https://api.github.com/users/username
        Returns a JSON string with keys: user, repos, events.
        """
        username = _extract_username(url)
        return await self.fetch_user(username)

    async def fetch_user(self, username: str) -> str:
        """Return combined user + repos + recent events as a JSON string."""
        async with httpx.AsyncClient(
            headers=_headers(),
            timeout=30,
            follow_redirects=True,
        ) as client:
            user_resp, repos_resp, events_resp = await _gather(
                client.get(f"{_API_BASE}/users/{username}"),
                client.get(f"{_API_BASE}/users/{username}/repos", params={"per_page": 30, "sort": "pushed"}),
                client.get(f"{_API_BASE}/users/{username}/events/public", params={"per_page": 30}),
            )

        _raise_for_status(user_resp, f"user {username!r}")
        user = user_resp.json()

        repos = repos_resp.json() if repos_resp.status_code == 200 else []
        events = events_resp.json() if events_resp.status_code == 200 else []

        payload = {
            "user": user,
            "repos": repos,
            "events": events,
        }
        return json.dumps(payload)

    async def fetch_org(self, org: str) -> str:
        """Return organization info + repos as a JSON string."""
        async with httpx.AsyncClient(headers=_headers(), timeout=30) as client:
            org_resp, repos_resp = await _gather(
                client.get(f"{_API_BASE}/orgs/{org}"),
                client.get(f"{_API_BASE}/orgs/{org}/repos", params={"per_page": 30, "sort": "pushed"}),
            )

        _raise_for_status(org_resp, f"org {org!r}")
        payload = {
            "org": org_resp.json(),
            "repos": repos_resp.json() if repos_resp.status_code == 200 else [],
        }
        return json.dumps(payload)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _gather(*coros):
    import asyncio
    return await asyncio.gather(*coros)


def _extract_username(url: str) -> str:
    """Parse github.com/username or api.github.com/users/username → username."""
    for prefix in ("https://github.com/", "https://api.github.com/users/"):
        if url.startswith(prefix):
            return url[len(prefix):].split("/")[0]
    # Treat bare string as username
    return url.strip("/").split("/")[-1]


def _raise_for_status(resp: httpx.Response, label: str) -> None:
    if resp.status_code == 404:
        raise GitHubNotFoundError(f"GitHub {label} not found")
    if resp.status_code == 403:
        raise GitHubRateLimitError(f"GitHub rate limit hit fetching {label}")
    resp.raise_for_status()


class GitHubNotFoundError(RuntimeError):
    pass


class GitHubRateLimitError(RuntimeError):
    pass

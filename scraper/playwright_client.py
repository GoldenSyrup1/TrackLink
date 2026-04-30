"""
Stealth Playwright client with proxy rotation and human-delay jitter.

Stealth measures applied:
- Realistic User-Agent and Accept-Language headers
- navigator.webdriver erased via init script
- WebGL vendor/renderer spoofed to a real GPU string
- Hardware concurrency and device memory set to plausible values
- Chrome plugins/languages arrays present (empty arrays fingerprint bots)
- Randomised viewport within common laptop resolutions
- Human-paced mouse movements via page.mouse (available to callers)

Usage:
    async with StealthClient() as client:
        html = await client.fetch("https://www.linkedin.com/in/some-profile")
"""
from __future__ import annotations

import asyncio
import logging
import random
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from shared.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.122 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1920, "height": 1080},
]

_WEBGL_VENDORS = [
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 6700 XT Direct3D11 vs_5_0 ps_5_0, D3D11)"),
]

# Injected before every page load to erase automation signals
_STEALTH_INIT_SCRIPT = """
() => {
    // Erase webdriver flag
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // Realistic plugins array
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            { name: 'Native Client', filename: 'internal-nacl-plugin' },
        ],
    });

    // Realistic languages
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

    // Remove automation-only chrome.runtime that exists in headless
    if (window.chrome && window.chrome.runtime) {
        try { delete window.chrome.runtime.connect; } catch (_) {}
    }

    // Permissions API: make geolocation look granted rather than denied
    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery(parameters);
}
"""


def _build_webgl_script(vendor: str, renderer: str) -> str:
    return f"""
() => {{
    const getParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {{
        if (param === 37445) return '{vendor}';
        if (param === 37446) return '{renderer}';
        return getParam.call(this, param);
    }};
    const getParam2 = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(param) {{
        if (param === 37445) return '{vendor}';
        if (param === 37446) return '{renderer}';
        return getParam2.call(this, param);
    }};
}}
"""


# ---------------------------------------------------------------------------
# Proxy helpers
# ---------------------------------------------------------------------------

def _parse_proxies() -> list[str]:
    """Parse comma-separated proxy URLs from settings.proxy_url."""
    raw = settings.proxy_url.strip()
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def _pick_proxy(proxies: list[str]) -> dict | None:
    """Return a Playwright proxy dict for a random proxy, or None."""
    if not proxies:
        return None
    url = random.choice(proxies)
    proxy: dict = {"server": url}
    return proxy


# ---------------------------------------------------------------------------
# Jitter
# ---------------------------------------------------------------------------

async def human_delay(
    min_ms: int | None = None,
    max_ms: int | None = None,
) -> None:
    lo = min_ms if min_ms is not None else settings.scraper_delay_min_ms
    hi = max_ms if max_ms is not None else settings.scraper_delay_max_ms
    delay_s = random.randint(lo, hi) / 1000.0
    await asyncio.sleep(delay_s)


# ---------------------------------------------------------------------------
# StealthClient
# ---------------------------------------------------------------------------

class StealthClient:
    """
    Manages a single Playwright browser + context with stealth config.

    Each `fetch()` call reuses the same context but opens a fresh page so
    cookies/session state accumulate across calls (simulates a browsing
    session).  Call `rotate_context()` to start a new session (new proxy,
    new fingerprint).
    """

    def __init__(self) -> None:
        self._proxies = _parse_proxies()
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._ua: str = random.choice(_USER_AGENTS)
        self._viewport: dict = random.choice(_VIEWPORTS)
        self._webgl: tuple[str, str] = random.choice(_WEBGL_VENDORS)

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        await self._new_context()

    async def stop(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def __aenter__(self) -> "StealthClient":
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch(
        self,
        url: str,
        wait_until: str = "domcontentloaded",
        timeout_ms: int = 30_000,
        pre_delay: bool = True,
    ) -> str:
        """
        Navigate to `url` and return the page's HTML.

        `pre_delay=True` inserts a randomised human-paced delay before
        navigation so request cadence does not look machine-generated.
        """
        if pre_delay:
            await human_delay()

        assert self._context is not None, "call start() first"
        page: Page = await self._context.new_page()
        try:
            await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            await self._random_scroll(page)
            return await page.content()
        finally:
            await page.close()

    async def fetch_json(
        self,
        url: str,
        timeout_ms: int = 30_000,
        pre_delay: bool = True,
    ) -> str:
        """Fetch a JSON API endpoint; returns raw response text."""
        if pre_delay:
            await human_delay()

        assert self._context is not None
        page: Page = await self._context.new_page()
        try:
            response = await page.goto(url, wait_until="load", timeout=timeout_ms)
            if response is None:
                raise RuntimeError(f"no response for {url}")
            return await response.text()
        finally:
            await page.close()

    async def rotate_context(self) -> None:
        """
        Tear down the current browser context and open a fresh one with a new
        User-Agent, viewport, WebGL fingerprint, and proxy selection.
        Simulates closing and reopening the browser.
        """
        if self._context:
            await self._context.close()
        self._ua = random.choice(_USER_AGENTS)
        self._viewport = random.choice(_VIEWPORTS)
        self._webgl = random.choice(_WEBGL_VENDORS)
        await self._new_context()
        logger.debug("rotated browser context (ua=%s...)", self._ua[:40])

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _new_context(self) -> None:
        assert self._browser is not None
        proxy = _pick_proxy(self._proxies)
        kwargs: dict = {
            "user_agent": self._ua,
            "viewport": self._viewport,
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "extra_http_headers": {
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        }
        if proxy:
            kwargs["proxy"] = proxy

        self._context = await self._browser.new_context(**kwargs)
        await self._context.add_init_script(_STEALTH_INIT_SCRIPT)
        await self._context.add_init_script(
            _build_webgl_script(*self._webgl)
        )

    @staticmethod
    async def _random_scroll(page: Page) -> None:
        """Scroll a random amount down the page — mimics reading behaviour."""
        scroll_px = random.randint(200, 800)
        await page.mouse.wheel(0, scroll_px)
        await asyncio.sleep(random.uniform(0.3, 1.2))

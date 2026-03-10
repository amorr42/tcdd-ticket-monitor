"""
Automatic JWT token extractor for TCDD.

The TCDD website fetches an anonymous public token from Keycloak on page load.
Playwright intercepts that token from outgoing Authorization headers — no login required.
Token is cached in-process and auto-refreshed 5 minutes before expiry.
"""

from __future__ import annotations
import asyncio
import random
import time
import threading
from dataclasses import dataclass

TOKEN_TTL = 55 * 60       # treat token as stale 5 min before actual JWT expiry (60 min)
TARGET_URL = "https://ebilet.tcddtasimacilik.gov.tr"

# Realistic Windows Chrome UAs — picked once per process, rotated on each fresh token fetch.
# Keeps the Playwright UA consistent with whatever profile the site sees.
PLAYWRIGHT_UA_POOL = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.207 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
]


@dataclass
class TokenCache:
    token: str = ""
    unit_id: str = "3895"
    fetched_at: float = 0.0

    def is_valid(self) -> bool:
        return bool(self.token) and (time.time() - self.fetched_at) < TOKEN_TTL

    def store(self, token: str, unit_id: str = "3895") -> None:
        self.token = token
        self.unit_id = unit_id
        self.fetched_at = time.time()
        print(f"[auth] Token captured. unit-id={unit_id}. Valid for ~{TOKEN_TTL // 60} min.")


token_cache = TokenCache()
refresh_lock = threading.Lock()


async def _capture_jwt_via_playwright() -> tuple[str, str]:
    """
    Headless Chromium session that intercepts the Keycloak JWT from outgoing API requests.
    Returns (jwt_token, unit_id) or ("", "3895") if interception fails.
    """
    from playwright.async_api import async_playwright

    intercepted: list[tuple[str, str]] = []
    user_agent = random.choice(PLAYWRIGHT_UA_POOL)

    async with async_playwright() as pw:
        # Prefer real Chrome binary — avoids headless Chromium fingerprint detection.
        try:
            browser = await pw.chromium.launch(
                headless=True,
                channel="chrome",
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
        except Exception:
            # Chrome not installed on this machine; bundled Chromium is the fallback.
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )

        ctx = await browser.new_context(user_agent=user_agent)
        page = await ctx.new_page()

        # Patch navigator.webdriver before any script runs on the page.
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined })"
        )

        def on_request(request):
            if intercepted:
                return
            auth_header = request.headers.get("authorization", "")
            if not auth_header:
                return
            # Header may be "Bearer <token>" or raw "<token>" depending on site version
            candidate = auth_header.removeprefix("Bearer ").strip()
            # Sanity check: must be a three-part JWT of reasonable length.
            if candidate.count(".") == 2 and len(candidate) > 100:
                unit = request.headers.get("unit-id", "3895")
                print(f"[auth] Intercepted token from: {request.url[:80]}")
                intercepted.append((candidate, unit))

        page.on("request", on_request)

        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)  # page fires several authenticated API calls on load

        if not intercepted:
            # Trigger a search interaction to provoke API calls with auth headers.
            for selector in [
                "input[placeholder*='Kalkış']",
                "input[placeholder*='nereden']",
                "input[name*='depart']",
                ".departure input",
                "input:first-of-type",
            ]:
                try:
                    el = await page.wait_for_selector(selector, timeout=2000)
                    if el:
                        await el.click()
                        await el.type("Ankara", delay=50)
                        await asyncio.sleep(1)
                        break
                except Exception:
                    continue
            await asyncio.sleep(3)

        await browser.close()

    return intercepted[0] if intercepted else ("", "3895")


def fetch_token() -> tuple[str, str]:
    """Synchronous entry point — runs the async Playwright session in a fresh event loop."""
    return asyncio.run(_capture_jwt_via_playwright())


def get_token(force_refresh: bool = False) -> tuple[str, str]:
    """
    Return a valid (jwt_token, unit_id) pair. Fetches or refreshes automatically.

    Args:
        force_refresh: Bypass the cache and capture a fresh token unconditionally.

    Raises:
        RuntimeError: If Playwright fails to intercept a token from the site.
    """
    with refresh_lock:
        if not force_refresh and token_cache.is_valid():
            return token_cache.token, token_cache.unit_id

        print("[auth] Fetching new token via Playwright...")
        token, unit_id = fetch_token()

        if not token:
            raise RuntimeError(
                "[auth] Failed to intercept JWT from TCDD. "
                "The site's request flow may have changed."
            )

        token_cache.store(token, unit_id)
        return token_cache.token, token_cache.unit_id


def invalidate() -> None:
    """Expire the cached token so the next get_token() call triggers a refresh."""
    with refresh_lock:
        token_cache.fetched_at = 0.0

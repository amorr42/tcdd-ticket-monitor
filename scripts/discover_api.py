"""
TCDD API Discovery Script — run once to intercept all network calls.

Usage:
    python scripts/discover_api.py

Opens ebilet.tcddtasimacilik.gov.tr in a visible browser window.
Perform a train search manually. All intercepted API calls are printed
with URL, headers, request body, and response. Use the output to
verify/update core/scanner.py endpoints.
"""

import json
import asyncio
from playwright.async_api import async_playwright

TARGET = "https://ebilet.tcddtasimacilik.gov.tr"
FILTER_KEYWORDS = ["tms", "train", "station", "availability", "seat", "bilet", "api"]

captured = []


async def handle_request(request):
    url = request.url
    if not any(k in url.lower() for k in FILTER_KEYWORDS):
        return
    try:
        body = request.post_data
    except Exception:
        body = None
    captured.append({
        "type": "REQUEST",
        "method": request.method,
        "url": url,
        "headers": dict(request.headers),
        "body": body,
    })


async def handle_response(response):
    url = response.url
    if not any(k in url.lower() for k in FILTER_KEYWORDS):
        return
    try:
        body = await response.text()
        try:
            body = json.loads(body)
        except Exception:
            pass
    except Exception:
        body = None
    captured.append({
        "type": "RESPONSE",
        "status": response.status,
        "url": url,
        "body": body,
    })


async def main():
    print("=" * 70)
    print("TCDD API Discovery — Playwright Network Interceptor")
    print("=" * 70)
    print(f"\nOpening: {TARGET}")
    print("Perform a train search in the browser.")
    print("Press ENTER in this terminal when done.\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        page.on("request", handle_request)
        page.on("response", handle_response)

        await page.goto(TARGET)
        input(">>> Press ENTER after completing a train search in the browser...\n")
        await browser.close()

    print("\n" + "=" * 70)
    print(f"Captured {len(captured)} relevant events")
    print("=" * 70)

    # Group by URL
    seen_urls = set()
    for event in captured:
        url = event["url"]
        if event["type"] == "REQUEST" and url not in seen_urls:
            seen_urls.add(url)
            print(f"\n--- {event['method']} {url}")
            # Print auth header if present
            auth = event["headers"].get("authorization", "")
            unit = event["headers"].get("unit-id", "")
            if auth:
                print(f"  Authorization: {auth[:60]}...")
            if unit:
                print(f"  unit-id: {unit}")
            if event["body"]:
                try:
                    parsed = json.loads(event["body"])
                    print(f"  Body: {json.dumps(parsed, indent=4, ensure_ascii=False)}")
                except Exception:
                    print(f"  Body: {event['body'][:200]}")

        elif event["type"] == "RESPONSE" and url in seen_urls:
            print(f"  Response [{event['status']}]:", end=" ")
            if isinstance(event["body"], dict):
                keys = list(event["body"].keys())
                print(f"keys={keys}")
            else:
                print(str(event["body"])[:100] if event["body"] else "(empty)")

    # Save full dump
    with open("scripts/api_discovery_output.json", "w", encoding="utf-8") as f:
        json.dump(captured, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nFull dump saved to: scripts/api_discovery_output.json")


if __name__ == "__main__":
    asyncio.run(main())

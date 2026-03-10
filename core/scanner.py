"""
TCDD train availability scanner.
Queries the API for a route + date, returns all trains with seat classes.

Sync requests via requests.Session (long-lived, connection-pooled).
Async variant via httpx for bot handler use.
"""

from __future__ import annotations

import random
from datetime import datetime

import httpx
import requests
import pytz

from core.auth import get_token, invalidate
from core.parser import parse_response, Train

ISTANBUL_TZ = pytz.timezone("Europe/Istanbul")
API_BASE = "https://web-api-prod-ytp.tcddtasimacilik.gov.tr"
AVAILABILITY_PATH = "/tms/train/train-availability"

BROWSER_PROFILES: dict[str, str] = {
    "chrome131": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "chrome130": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "chrome124": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "safari17_2": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15"
    ),
    "firefox133": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
        "Gecko/20100101 Firefox/133.0"
    ),
}


class TCDDClient:
    """Synchronous TCDD API client with persistent session and auto-auth."""

    def __init__(
        self,
        stations: dict[str, int],
        environment: str = "dev",
        user_id: int = 1,
        timeout: int = 30,
    ):
        self.stations = stations
        self.environment = environment
        self.user_id = user_id
        self.timeout = timeout

        self.profile = random.choice(list(BROWSER_PROFILES))
        self.user_agent = BROWSER_PROFILES[self.profile]

        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
            "Origin": "https://ebilet.tcddtasimacilik.gov.tr",
            "Referer": "https://ebilet.tcddtasimacilik.gov.tr/",
            "Connection": "keep-alive",
        })

        # Suppress InsecureRequestWarning from urllib3
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def rotate_profile(self) -> None:
        self.profile = random.choice(list(BROWSER_PROFILES))
        self.user_agent = BROWSER_PROFILES[self.profile]
        self.session.headers["User-Agent"] = self.user_agent

    def scan_route(
        self,
        dep_name: str,
        arr_name: str,
        date: str,
        token: str = "",
        auto_auth: bool = True,
    ) -> list[Train]:
        if auto_auth and not token:
            token, unit_id = get_token()
        else:
            unit_id = "3895"

        dep_id = self.stations.get(dep_name)
        arr_id = self.stations.get(arr_name)
        if dep_id is None:
            print(f"[scanner] Unknown departure station: {dep_name!r}")
            return []
        if arr_id is None:
            print(f"[scanner] Unknown arrival station: {arr_name!r}")
            return []

        date_api = self._normalize_date(date)
        if not date_api:
            return []

        payload = self._build_payload(dep_id, dep_name, arr_id, arr_name, date_api)
        params = {"environment": self.environment, "userId": self.user_id}
        auth_headers = {"Authorization": f"Bearer {token}", "unit-id": unit_id}

        resp = self._post(payload, params, auth_headers)
        if resp is None:
            return []

        # 401/403 → invalidate + retry once
        if resp.status_code in (401, 403):
            print(f"[scanner] Auth error {resp.status_code} — refreshing token...")
            if not auto_auth:
                return []
            invalidate()
            token, unit_id = get_token(force_refresh=True)
            auth_headers = {"Authorization": f"Bearer {token}", "unit-id": unit_id}
            self.rotate_profile()
            resp = self._post(payload, params, auth_headers)
            if resp is None or resp.status_code != 200:
                print(f"[scanner] Retry failed")
                return []

        if resp.status_code != 200:
            print(f"[scanner] API error {resp.status_code}: {resp.text[:200]}")
            return []

        trains = parse_response(resp.json())
        print(f"[scanner] {dep_name} → {arr_name} on {date_api}: {len(trains)} trains found")
        return trains

    def _post(
        self,
        payload: dict,
        params: dict,
        auth_headers: dict,
    ) -> requests.Response | None:
        try:
            return self.session.post(
                API_BASE + AVAILABILITY_PATH,
                json=payload,
                params=params,
                headers=auth_headers,
                timeout=self.timeout,
            )
        except requests.Timeout:
            print("[scanner] Request timed out")
            return None
        except requests.ConnectionError as exc:
            print(f"[scanner] Connection error: {exc}")
            return None

    @staticmethod
    def _normalize_date(date: str) -> str:
        try:
            if "-" in date and len(date.split("-")[0]) == 4:
                dt = datetime.strptime(date, "%Y-%m-%d")
            else:
                dt = datetime.strptime(date, "%d-%m-%Y")
            return dt.strftime("%d-%m-%Y 00:00:00")
        except ValueError as exc:
            print(f"[scanner] Invalid date format {date!r}: {exc}")
            return ""

    @staticmethod
    def _build_payload(
        dep_id: int, dep_name: str,
        arr_id: int, arr_name: str,
        date_str: str,
    ) -> dict:
        return {
            "searchRoutes": [
                {
                    "departureStationId": dep_id,
                    "departureStationName": dep_name,
                    "arrivalStationId": arr_id,
                    "arrivalStationName": arr_name,
                    "departureDate": date_str,
                }
            ],
            "passengerTypeCounts": [{"id": 0, "count": 1}],
            "searchReservation": False,
        }


class AsyncTCDDClient:
    """Async TCDD API client using httpx — for bot handler use."""

    def __init__(
        self,
        stations: dict[str, int],
        environment: str = "dev",
        user_id: int = 1,
        timeout: int = 30,
    ):
        self.stations = stations
        self.environment = environment
        self.user_id = user_id
        self.timeout = timeout

        profile = random.choice(list(BROWSER_PROFILES))
        self.user_agent = BROWSER_PROFILES[profile]

    async def scan_route(
        self,
        dep_name: str,
        arr_name: str,
        date: str,
        token: str = "",
        auto_auth: bool = True,
    ) -> list[Train]:
        if auto_auth and not token:
            token, unit_id = get_token()
        else:
            unit_id = "3895"

        dep_id = self.stations.get(dep_name)
        arr_id = self.stations.get(arr_name)
        if dep_id is None or arr_id is None:
            return []

        date_api = TCDDClient._normalize_date(date)
        if not date_api:
            return []

        payload = TCDDClient._build_payload(dep_id, dep_name, arr_id, arr_name, date_api)
        params = {"environment": self.environment, "userId": self.user_id}
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
            "Origin": "https://ebilet.tcddtasimacilik.gov.tr",
            "Referer": "https://ebilet.tcddtasimacilik.gov.tr/",
            "Authorization": f"Bearer {token}",
            "unit-id": unit_id,
        }

        async with httpx.AsyncClient(verify=False, timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    API_BASE + AVAILABILITY_PATH,
                    json=payload,
                    params=params,
                    headers=headers,
                )
            except httpx.TimeoutException:
                print("[scanner:async] Request timed out")
                return []
            except httpx.ConnectError as exc:
                print(f"[scanner:async] Connection error: {exc}")
                return []

            if resp.status_code in (401, 403) and auto_auth:
                invalidate()
                token, unit_id = get_token(force_refresh=True)
                headers["Authorization"] = f"Bearer {token}"
                headers["unit-id"] = unit_id
                try:
                    resp = await client.post(
                        API_BASE + AVAILABILITY_PATH,
                        json=payload,
                        params=params,
                        headers=headers,
                    )
                except (httpx.TimeoutException, httpx.ConnectError):
                    return []

            if resp.status_code != 200:
                return []

        trains = parse_response(resp.json())
        print(f"[scanner:async] {dep_name} → {arr_name}: {len(trains)} trains")
        return trains


# ── Module-level compat: scan_route() free function ──────────
# Used by scheduler._poll_rule() — creates a one-shot client per call.
# Scheduler should ideally hold a TCDDClient instance, but this keeps
# backwards compat until scheduler is refactored.

def scan_route(
    dep_name: str,
    arr_name: str,
    date: str,
    stations: dict,
    token: str = "",
    unit_id: str = "3895",
    environment: str = "dev",
    user_id: int = 1,
    timeout: int = 30,
    auto_auth: bool = True,
) -> list[Train]:
    client = TCDDClient(
        stations=stations,
        environment=environment,
        user_id=user_id,
        timeout=timeout,
    )
    return client.scan_route(dep_name, arr_name, date, token=token, auto_auth=auto_auth)

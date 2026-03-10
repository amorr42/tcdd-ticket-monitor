"""
Telegram alert sender with rate limiting and persistent session.
"""

from __future__ import annotations

import time

import requests

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
RATE_LIMIT_SECONDS = 900  # 15 min per train


class TelegramAlerter:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = str(chat_id)
        self.last_sent: dict[str, float] = {}  # train_id → timestamp

        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def is_rate_limited(self, train_id: str) -> bool:
        last = self.last_sent.get(train_id, 0)
        return (time.time() - last) < RATE_LIMIT_SECONDS

    def send(self, train_id: str, message: str, force: bool = False) -> bool:
        """Send alert. Returns True if sent, False if rate-limited or failed."""
        if not force and self.is_rate_limited(train_id):
            return False

        url = TELEGRAM_API.format(token=self.bot_token)
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
        }
        try:
            resp = self.session.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                self.last_sent[train_id] = time.time()
                return True
            print(f"[telegram] Send failed {resp.status_code}: {resp.text[:100]}")
            return False
        except requests.Timeout:
            print("[telegram] Request timed out")
            return False
        except requests.ConnectionError as exc:
            print(f"[telegram] Connection error: {exc}")
            return False

    def build_message(
        self,
        dep_name: str,
        arr_name: str,
        date: str,
        train_summary: str,
        classes_opened: dict[str, int],
    ) -> str:
        lines = [
            "<b>Seat Available — TCDD</b>",
            f"Route: {dep_name} → {arr_name}",
            f"Date: {date}",
            f"Train: {train_summary}",
            "",
            "<b>Available classes:</b>",
        ]
        for cls, seats in classes_opened.items():
            lines.append(f"  • {cls}: {seats} seat(s)")

        lines.append("")
        lines.append("<a href='https://ebilet.tcddtasimacilik.gov.tr'>Book now</a>")
        return "\n".join(lines)

    def test(self) -> bool:
        """Send a test message to verify bot token and chat ID."""
        return self.send(
            "__test__",
            "TCDD Monitor: connection test OK",
            force=True,
        )

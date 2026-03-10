"""WatchService — thread-safe watch rule management with persistence."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from core.scheduler import WatchRule
from bot.stations import StationResolver


class WatchService:
    def __init__(self, stations: dict[str, int], watches_path: str = "data/watches.json"):
        self.resolver = StationResolver(stations)
        self._path = Path(watches_path)
        self._lock = threading.Lock()
        self.watches: list[WatchRule] = []

    # ── public API (all lock-guarded) ──────────────────────────

    def add_watch(
        self,
        dep: str,
        arr: str,
        date: str,
        time_from: str = "00:00",
        time_to: str = "23:59",
        poll_interval: int = 120,
    ) -> WatchRule:
        """Add a new watch rule. Raises ValueError if station not found."""
        dep_exact = self.resolver.exact_match(dep)
        if not dep_exact:
            raise ValueError(f"Unknown departure station: {dep}")
        arr_exact = self.resolver.exact_match(arr)
        if not arr_exact:
            raise ValueError(f"Unknown arrival station: {arr}")

        rule = WatchRule(
            dep=dep_exact,
            arr=arr_exact,
            date=date,
            time_from=time_from,
            time_to=time_to,
            poll_interval=poll_interval,
        )
        with self._lock:
            self.watches.append(rule)
            self._save_unlocked()
        return rule

    def remove_watch(self, index: int) -> WatchRule | None:
        """Remove watch by 1-based index. Returns removed rule or None."""
        with self._lock:
            idx = index - 1
            if 0 <= idx < len(self.watches):
                rule = self.watches.pop(idx)
                self._save_unlocked()
                return rule
            return None

    def list_watches(self) -> list[tuple[int, WatchRule]]:
        """Return list of (1-based index, rule)."""
        with self._lock:
            return [(i + 1, r) for i, r in enumerate(self.watches)]

    def get_snapshot(self) -> list[WatchRule]:
        """Thread-safe shallow copy for scheduler."""
        with self._lock:
            return list(self.watches)

    # ── persistence ────────────────────────────────────────────

    def save(self) -> None:
        with self._lock:
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        """Atomic write: tmp file + os.replace. Caller must hold lock."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        data = [
            {
                "from": r.dep,
                "to": r.arr,
                "date": r.date,
                "time_from": r.time_from,
                "time_to": r.time_to,
                "poll_interval": r.poll_interval,
            }
            for r in self.watches
        ]
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(str(tmp), str(self._path))

    def load(self) -> None:
        """Load watches from JSON file if it exists."""
        if not self._path.exists():
            return
        with open(self._path, encoding="utf-8") as f:
            data = json.load(f)
        with self._lock:
            self.watches = [
                WatchRule(
                    dep=w["from"],
                    arr=w["to"],
                    date=w["date"],
                    time_from=w.get("time_from", "00:00"),
                    time_to=w.get("time_to", "23:59"),
                    poll_interval=w.get("poll_interval", 120),
                )
                for w in data
            ]

    def seed_from_config(self, watches_cfg: list[dict]) -> None:
        """Seed watches from config.yaml watch list."""
        with self._lock:
            self.watches = [
                WatchRule(
                    dep=w["from"],
                    arr=w["to"],
                    date=w["date"],
                    time_from=w.get("time_from", "00:00"),
                    time_to=w.get("time_to", "23:59"),
                    poll_interval=w.get("poll_interval", 120),
                )
                for w in watches_cfg
            ]
            self._save_unlocked()

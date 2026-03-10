"""
Poll scheduler — monitors multiple routes, detects seat openings (0 → >0).
"""

from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from core.scanner import scan_route
from core.parser import Train
from alerts.telegram import TelegramAlerter


@dataclass
class WatchRule:
    dep: str
    arr: str
    date: str
    time_from: str = "00:00"   # HH:MM
    time_to: str = "23:59"
    poll_interval: int = 120   # seconds


@dataclass
class Scheduler:
    rules: list[WatchRule]
    alerter: TelegramAlerter
    stations: dict
    environment: str = "dev"
    user_id: int = 1
    watch_service: object = None  # optional WatchService for dynamic rules

    # State: (rule_key, train_id) → seats_by_class at last poll
    _state: dict = field(default_factory=dict)
    _next_poll: dict = field(default_factory=dict)  # rule_key → next poll timestamp

    def _rule_key(self, rule: WatchRule) -> str:
        return f"{rule.dep}|{rule.arr}|{rule.date}"

    def _filter_by_time(self, trains: list[Train], rule: WatchRule) -> list[Train]:
        """Keep only trains within the desired time window."""
        try:
            t_from = datetime.strptime(rule.time_from, "%H:%M").time()
            t_to = datetime.strptime(rule.time_to, "%H:%M").time()
        except ValueError:
            return trains
        return [
            t for t in trains
            if t_from <= t.departure_time.time() <= t_to
        ]

    def _poll_rule(self, rule: WatchRule):
        key = self._rule_key(rule)
        trains = scan_route(
            dep_name=rule.dep,
            arr_name=rule.arr,
            date=rule.date,
            stations=self.stations,
            environment=self.environment,
            user_id=self.user_id,
            auto_auth=True,
        )
        trains = self._filter_by_time(trains, rule)

        for train in trains:
            state_key = f"{key}|{train.train_id}"
            prev = self._state.get(state_key, {})
            curr = train.seats_by_class()

            # Detect 0 → >0 changes per class
            newly_opened = {
                cls: seats
                for cls, seats in curr.items()
                if seats > 0 and prev.get(cls, 0) == 0
            }

            if newly_opened:
                msg = self.alerter.build_message(
                    dep_name=rule.dep,
                    arr_name=rule.arr,
                    date=rule.date,
                    train_summary=train.summary(),
                    classes_opened=newly_opened,
                )
                sent = self.alerter.send(train_id=state_key, message=msg)
                if sent:
                    print(f"[scheduler] Alert sent: {train.summary()} — {newly_opened}")

            self._state[state_key] = curr

    def run_once(self):
        """Poll all rules that are due now."""
        active_rules = self.watch_service.get_snapshot() if self.watch_service else self.rules
        now = time.time()
        for rule in active_rules:
            key = self._rule_key(rule)
            if now >= self._next_poll.get(key, 0):
                print(f"[scheduler] Polling: {rule.dep} → {rule.arr} on {rule.date}")
                self._poll_rule(rule)
                self._next_poll[key] = now + rule.poll_interval

    def run(self):
        """Main loop — runs forever."""
        print("[scheduler] Starting monitor loop. Press Ctrl+C to stop.\n")
        while True:
            self.run_once()
            time.sleep(5)  # tight loop, actual pacing via _next_poll

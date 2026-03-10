"""
TCDD Ticket Monitor — entry point.

Usage:
    python main.py                  # start bot + monitoring loop
    python main.py --test-telegram  # send test Telegram message and exit
    python main.py --scan-once      # poll all rules once and exit
"""

import argparse
import json
import sys
import threading
from pathlib import Path

import yaml

from alerts.telegram import TelegramAlerter
from bot.app import create_bot
from bot.service import WatchService
from core.scheduler import Scheduler, WatchRule


def load_config(path: str = "config.yaml") -> dict:
    cfg_path = Path(path)
    if not cfg_path.exists():
        print(f"ERROR: Config file not found: {path}")
        print("Copy config.example.yaml to config.yaml and fill in your values.")
        sys.exit(1)
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_stations(path: str = "data/stations.json") -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_scheduler(cfg: dict, stations: dict) -> Scheduler:
    tg_cfg = cfg.get("telegram", {})
    alerter = TelegramAlerter(
        bot_token=tg_cfg["bot_token"],
        chat_id=tg_cfg["chat_id"],
    )

    rules = []
    for w in cfg.get("watches", []):
        rules.append(WatchRule(
            dep=w["from"],
            arr=w["to"],
            date=w["date"],
            time_from=w.get("time_from", "00:00"),
            time_to=w.get("time_to", "23:59"),
            poll_interval=w.get("poll_interval", 120),
        ))

    return Scheduler(
        rules=rules,
        alerter=alerter,
        stations=stations,
        environment=cfg.get("environment", "dev"),
        user_id=cfg.get("user_id", 1),
    )


def main():
    parser = argparse.ArgumentParser(description="TCDD Ticket Monitor")
    parser.add_argument("--test-telegram", action="store_true",
                        help="Send a test Telegram message and exit")
    parser.add_argument("--scan-once", action="store_true",
                        help="Poll all watch rules once and exit")
    parser.add_argument("--config", default="config.yaml",
                        help="Path to config file (default: config.yaml)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    stations = load_stations()
    scheduler = build_scheduler(cfg, stations)

    if args.test_telegram:
        print("Sending test Telegram message...")
        ok = scheduler.alerter.test()
        print("OK — message sent." if ok else "FAILED — check bot_token and chat_id.")
        return

    if args.scan_once:
        print("Running single poll for all watch rules...")
        scheduler.run_once()
        print("Done.")
        return

    # Set up dynamic watch management
    tg_cfg = cfg.get("telegram", {})
    watch_service = WatchService(stations)
    watch_service.load()
    if not watch_service.watches:
        watch_service.seed_from_config(cfg.get("watches", []))

    scheduler.watch_service = watch_service

    # Scheduler on daemon thread, bot on main thread
    scheduler_thread = threading.Thread(target=scheduler.run, daemon=True)
    scheduler_thread.start()

    print("[main] Starting Telegram bot. Send /start in chat for the menu.")
    auth_chat_id = tg_cfg.get("user_chat_id") or tg_cfg["chat_id"]
    bot_app = create_bot(tg_cfg["bot_token"], auth_chat_id, watch_service, scheduler)
    bot_app.run_polling()


if __name__ == "__main__":
    main()

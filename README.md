# TCDD Ticket Monitor

Monitors TCDD (Turkish State Railways) train routes and sends a Telegram alert the moment a seat opens on a previously full train — across **all cabin classes**.

## How It Works

1. Interactive Telegram bot — pick route, date, and train via inline buttons
2. Polls the TCDD availability API on a configurable interval per watch rule
3. Detects **0 → >0 seat** transitions in any class and fires an alert
4. Auto-fetches authentication tokens via headless Playwright — no manual steps

## Features

- **Menu-driven Telegram UX** — no typing station names or dates
- **Live train search** — fetches real-time seat availability via async httpx
- **Multi-route support** — watch multiple routes and dates simultaneously
- **All-class detection** — economy, business, sleeper, etc.
- **Rate-limited alerts** — max 1 alert per train per 15 minutes
- **Fuzzy station search** — type partial names, get suggestions
- **Auto-auth** — JWT tokens captured and refreshed automatically via Playwright

## Requirements

- Python 3.10+
- A Telegram bot (create via [@BotFather](https://t.me/BotFather))
- Playwright Chromium (`playwright install chromium`)

## Installation

```bash
cd tcdd-monitor
pip install -r requirements.txt
playwright install chromium
cp config.example.yaml config.yaml
# Edit config.yaml with your Telegram bot token and chat IDs
```

## Configuration

Edit `config.yaml` — see `config.example.yaml` for all available options.

Key fields:
- `telegram.bot_token` — your Telegram bot token from @BotFather
- `telegram.chat_id` — channel/group ID for alert messages
- `telegram.user_chat_id` — your personal Telegram user ID for the interactive menu

## Usage

```bash
# Start the bot + monitoring loop
python main.py

# Verify Telegram connection
python main.py --test-telegram

# Run one poll cycle and exit
python main.py --scan-once
```

### Telegram Bot Commands

- `/start` — Main menu with interactive buttons
- `/help` — Same as /start

### Bot Flow

```
/start → Main Menu: [New Alarm] [My Alarms] [Status]
  → Pick departure station (popular grid + fuzzy search)
  → Pick arrival station
  → Pick date (today + 6 days)
  → Bot fetches live trains with seat counts
  → Tap alarm on sold-out trains → scheduler monitors in background
  → Alert fires when seats open
```

## Architecture

```
main.py                     Entry point — bot + scheduler threads
bot/
  app.py                    Telegram application builder
  handlers.py               Menu-driven callback handlers
  service.py                Thread-safe watch rule management
  stations.py               Fuzzy station resolver + popular stations
core/
  scanner.py                TCDDClient (sync) + AsyncTCDDClient (httpx)
  scheduler.py              Poll loop — detects seat openings
  parser.py                 API response → Train objects
  auth.py                   JWT capture via Playwright
alerts/
  telegram.py               Alert sender with rate limiting
```

## License

MIT

# Xilma Telegram Bot (ptb)

A minimal echo bot using `python-telegram-bot` (ptb). The bot’s name is **Xilma**.

## Setup

1. Create a bot with @BotFather and copy the token.
2. Create a virtualenv and install deps:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Create a `.env` file or export your token and run:

Example `.env`:

```
TELEGRAM_BOT_TOKEN="<your token>"
ADMIN_USER_ID="<admin user id>"
```

Environment variables take precedence over `.env` if both are set. Then run:

```bash
python bot.py
```

## What it does

- `/start` — greeting
- `/help` — commands
- `/admin` — admin check (requires `ADMIN_USER_ID`)
- Any text message — echo

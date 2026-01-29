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

3. Export your token and run:

```bash
export TELEGRAM_BOT_TOKEN="<your token>"
python bot.py
```

## What it does

- `/start` — greeting
- `/help` — commands
- Any text message — echo

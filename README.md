# Xilma Telegram Bot (PTB + Single AI API)

A production-ready Telegram bot using `python-telegram-bot` (async) that routes user prompts to a OpenAI-compatible API.

## Highlights

- Clean single config system with runtime admin edits
- Glass-style admin panel with inline buttons
- Persian (Farsi) UI text
- Structured logging + safe error handling

## Setup

1. Create a bot with @BotFather and copy the token.
2. Create a virtualenv and install deps:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Create a `.env` file (or export env vars):

```env
# Mandatory
DATABASE_URL="postgresql://xilma:xilma@localhost:5432/xilma"
TELEGRAM_BOT_TOKEN="<telegram token>"
ADMIN_USER_ID="<admin user id>"
```

Then run:

```bash
python bot.py
```

## Commands (Persian UI)

- `/start` — شروع
- `/help` — راهنما
- `/new` — پاک‌کردن گفتگو
- `/model <name>` — انتخاب مدل پاسخ‌دهی
- `/admin` — پنل مدیریت شیشه‌ای (فقط مدیر)

`/model` accepts any model identifier supported by your API (e.g. `gpt-4o`).

## Admin Panel UX

Open `/admin` to see a glass-style panel with all settings and their current values.
Each setting is clickable. After tapping a setting, the bot asks for a new value and provides a Back button.
Validation is strict (numeric limits, enums, format checks). Invalid input shows a clear error and allows retry.
Settings are stored in PostgreSQL and loaded at startup; update them via the admin panel.

Sponsor channels are enforced for regular users. Admins are exempt.
You can update sponsor channels from the admin panel using the `SPONSOR_CHANNELS` setting.
The panel includes dedicated Sponsor buttons for Add / Edit / Remove, plus quick add by typing.

## Architecture Overview

- `xilma/config.py` — unified config store + validation
- `xilma/ai_client.py` — direct API client (single service)
- `xilma/db.py` — PostgreSQL access + migrations
- `xilma/handlers/` — Telegram handlers (user + admin)
- `xilma/logging_setup.py` — structured logging

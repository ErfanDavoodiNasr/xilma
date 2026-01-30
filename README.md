# Xilma Telegram Bot (PTB + AvalAI)

A production-ready, modular Telegram bot using `python-telegram-bot` (async) that routes user prompts to LLMs via AvalAI’s OpenAI-compatible API.

## Features

- Modular architecture: config, providers, services, handlers, logging
- Sponsor channel gating with dynamic membership checks
- Admin-only sponsor management commands
- Persian (Farsi) UI text
- Structured logging and safe error handling
- LLM provider abstraction (AvalAI today, more later)

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
TELEGRAM_BOT_TOKEN="<telegram token>"
AVALAI_API_KEY="<avalai api key>"
# Optional base URL
# AVALAI_BASE_URL="https://api.avalai.ir"
ADMIN_USER_ID="<admin user id>"
# Or multiple admins:
# ADMIN_USER_IDS="123,456"

# Sponsor channels (public usernames only, comma-separated)
SPONSOR_CHANNELS="@channel1,@channel2"
# Optional storage file
SPONSOR_CHANNELS_FILE="sponsors.json"

# LLM defaults
DEFAULT_PROVIDER="avalai"
DEFAULT_MODEL="gpt-4o"
# Optional fallback
# FALLBACK_MODEL="gpt-4o-mini"

# Retry behavior
# MAX_RETRIES="1"
# RETRY_BACKOFF="0.5"

# Optional sampling overrides
# TEMPERATURE="0.7"
# MAX_TOKENS="512"
# TOP_P="0.9"

# Conversation memory
# MAX_HISTORY_MESSAGES="12"

# Logging
LOG_LEVEL="INFO"
# LOG_FORMAT="text" | "json" | "both" | "json,text"
LOG_ANONYMIZE_USER_IDS="true"
LOG_MESSAGE_BODY="true"
LOG_MESSAGE_HEADERS="true"
```

Then run:

```bash
python bot.py
```

## Commands (Persian UI)

- `/start` — شروع
- `/help` — راهنما
- `/new` — پاک کردن گفتگو
- `/model <name>` — انتخاب مدل پاسخ‌دهی

`/model` accepts any AvalAI model identifier (e.g. `gpt-4o`, `gemini-2.5-pro`). The bot does not validate model names.

Admin-only:
- `/admin`
- `/status`
- `/sponsors`
- `/sponsor_add @channel`
- `/sponsor_remove @channel`

## Sponsor Gating Notes

- The bot checks membership dynamically using Telegram’s API.
- Sponsor channels must be public usernames (e.g. `@channel`).
- Invite links are not supported for membership checks.
- Changes made via admin commands are persisted in `sponsors.json` (or the file set via `SPONSOR_CHANNELS_FILE`).

## Architecture Overview

- `xilma/config.py` — settings loader
- `xilma/providers/` — LLM provider implementations
- `xilma/services/` — sponsor gating
- `xilma/handlers/` — Telegram handlers
- `xilma/llm_client.py` — unified LLM routing
- `xilma/logging_setup.py` — structured logging

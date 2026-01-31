from __future__ import annotations

from dataclasses import dataclass
import asyncio
import logging
from typing import Iterable

from telegram import InlineKeyboardButton
from telegram.error import TelegramError

from xilma.errors import UserVisibleError
from xilma import texts


@dataclass(frozen=True)
class SponsorChannel:
    raw: str
    chat_id: str
    label: str
    url: str


def _clean_channel(raw: str) -> str:
    return raw.strip()


def _normalize_channels(raw_items: Iterable[str]) -> list[SponsorChannel]:
    channels: list[SponsorChannel] = []
    for raw in raw_items:
        try:
            channel = normalize_channel(raw)
        except ValueError as exc:
            raise UserVisibleError(texts.SPONSOR_INVALID) from exc
        if any(existing.chat_id == channel.chat_id for existing in channels):
            continue
        channels.append(channel)
    return channels


def normalize_channel(raw: str) -> SponsorChannel:
    cleaned = _clean_channel(raw)
    if not cleaned:
        raise ValueError("empty")

    if cleaned.startswith("https://t.me/") or cleaned.startswith("http://t.me/"):
        cleaned = cleaned.split("t.me/", 1)[1]
    if cleaned.startswith("t.me/"):
        cleaned = cleaned.split("t.me/", 1)[1]

    if cleaned.startswith("+") or cleaned.startswith("joinchat/"):
        raise ValueError("invite links are not supported")

    username = cleaned[1:] if cleaned.startswith("@") else cleaned

    if not username.replace("_", "").isalnum():
        raise ValueError("invalid username")

    label = f"@{username}"
    url = f"https://t.me/{username}"
    return SponsorChannel(raw=label, chat_id=label, label=label, url=url)


def parse_channels_csv(raw_csv: str) -> list[SponsorChannel]:
    raw_items = [item.strip() for item in raw_csv.split(",") if item.strip()]
    return _normalize_channels(raw_items)


class SponsorService:
    def __init__(self, initial_channels: Iterable[str]) -> None:
        self._logger = logging.getLogger("xilma.sponsor")
        self._channels: list[SponsorChannel] = []
        self._membership_retries = 1
        self._membership_backoff = 0.5
        self.set_channels(list(initial_channels))

    def list_channels(self) -> list[SponsorChannel]:
        return list(self._channels)

    def set_channels(self, raw_list: list[str]) -> None:
        self._channels = _normalize_channels(raw_list)

    def set_channels_csv(self, raw_csv: str) -> None:
        self._channels = parse_channels_csv(raw_csv)

    def add_channel(self, raw: str) -> None:
        try:
            channel = normalize_channel(raw)
        except ValueError as exc:
            raise UserVisibleError(texts.SPONSOR_INVALID) from exc
        if any(existing.chat_id == channel.chat_id for existing in self._channels):
            raise UserVisibleError(texts.SPONSOR_ALREADY_EXISTS)
        self._channels.append(channel)

    def remove_channel(self, raw: str) -> None:
        try:
            channel = normalize_channel(raw)
        except ValueError as exc:
            raise UserVisibleError(texts.SPONSOR_INVALID) from exc
        before = len(self._channels)
        self._channels = [
            existing for existing in self._channels if existing.chat_id != channel.chat_id
        ]
        if len(self._channels) == before:
            raise UserVisibleError(texts.SPONSOR_NOT_FOUND)

    def build_buttons(self) -> list[list[InlineKeyboardButton]]:
        return [[InlineKeyboardButton(text=channel.label, url=channel.url)] for channel in self._channels]

    async def is_member(self, bot, user_id: int) -> bool:
        if not self._channels:
            return True
        for channel in self._channels:
            member = None
            last_error: TelegramError | None = None
            for attempt in range(self._membership_retries + 1):
                try:
                    member = await bot.get_chat_member(
                        chat_id=channel.chat_id, user_id=user_id
                    )
                    last_error = None
                    break
                except TelegramError as exc:
                    last_error = exc
                    if attempt < self._membership_retries:
                        await asyncio.sleep(self._membership_backoff * (2**attempt))
                        continue
            if last_error is not None:
                self._logger.warning(
                    "membership_check_failed",
                    extra={"channel": channel.chat_id, "error": str(last_error)},
                )
                return True
            if member.status not in {"member", "administrator", "creator"}:
                return False
        return True

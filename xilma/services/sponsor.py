from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from typing import Iterable

from telegram import InlineKeyboardButton
from telegram.error import TelegramError

from xilma.errors import UserVisibleError
from xilma import texts


@dataclass(frozen=True)
class SponsorChannel:
    raw: str
    chat_id: str | int
    label: str
    url: str


def _clean_channel(raw: str) -> str:
    return raw.strip()


def normalize_channel(raw: str) -> SponsorChannel:
    cleaned = _clean_channel(raw)
    if not cleaned:
        raise ValueError("empty")

    if cleaned.startswith("https://t.me/") or cleaned.startswith("http://t.me/"):
        cleaned = cleaned.split("t.me/", 1)[1]
    if cleaned.startswith("t.me/"):
        cleaned = cleaned.split("t.me/", 1)[1]

    if cleaned.startswith("+") or cleaned.startswith("joinchat/"):
        raise ValueError("invite links are not supported for membership checks")

    if cleaned.startswith("@"):
        username = cleaned[1:]
    else:
        username = cleaned

    if username.lstrip("-").isdigit():
        raise ValueError("numeric channel ids are not supported")

    if not username.replace("_", "").isalnum():
        raise ValueError("invalid username")

    label = f"@{username}"
    url = f"https://t.me/{username}"
    return SponsorChannel(raw=label, chat_id=label, label=label, url=url)


class SponsorService:
    def __init__(self, storage_path: str, initial_channels: Iterable[str]) -> None:
        self._storage_path = storage_path
        self._logger = logging.getLogger("xilma.sponsor")
        self._channels: list[SponsorChannel] = []
        self._load(initial_channels)

    def _load(self, initial_channels: Iterable[str]) -> None:
        raw_channels: list[str] = []
        if os.path.exists(self._storage_path):
            try:
                with open(self._storage_path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, list):
                    raw_channels = [str(item) for item in data]
            except (OSError, json.JSONDecodeError) as exc:
                self._logger.warning("failed_to_load_sponsors", extra={"error": str(exc)})
        if not raw_channels:
            raw_channels = list(initial_channels)

        self._channels = []
        for raw in raw_channels:
            try:
                self._channels.append(normalize_channel(raw))
            except ValueError:
                self._logger.warning("invalid_sponsor_channel", extra={"channel": raw})
        self._persist()

    def _persist(self) -> None:
        try:
            with open(self._storage_path, "w", encoding="utf-8") as handle:
                json.dump([channel.raw for channel in self._channels], handle, ensure_ascii=False, indent=2)
        except OSError as exc:
            self._logger.error("failed_to_save_sponsors", extra={"error": str(exc)})

    def list_channels(self) -> list[SponsorChannel]:
        return list(self._channels)

    def add_channel(self, raw: str) -> None:
        try:
            channel = normalize_channel(raw)
        except ValueError as exc:
            raise UserVisibleError(texts.SPONSOR_INVALID) from exc

        if any(existing.chat_id == channel.chat_id for existing in self._channels):
            raise UserVisibleError(texts.SPONSOR_ALREADY_EXISTS)

        self._channels.append(channel)
        self._persist()

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
        self._persist()

    def build_buttons(self) -> list[list[InlineKeyboardButton]]:
        return [[InlineKeyboardButton(text=channel.label, url=channel.url)] for channel in self._channels]

    async def is_member(self, bot, user_id: int) -> bool:
        if not self._channels:
            return True

        for channel in self._channels:
            try:
                member = await bot.get_chat_member(chat_id=channel.chat_id, user_id=user_id)
            except TelegramError as exc:
                self._logger.warning(
                    "membership_check_failed",
                    extra={"channel": channel.chat_id, "error": str(exc)},
                )
                return False

            if member.status not in {"member", "administrator", "creator"}:
                return False
        return True

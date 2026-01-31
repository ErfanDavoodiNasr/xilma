from __future__ import annotations

from pathlib import Path
import os
from typing import Any

import asyncpg


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def load_database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        raise SystemExit("DATABASE_URL is not set")
    return value


class Database:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(dsn=self._dsn, min_size=1, max_size=5)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def migrate(self) -> None:
        await self.connect()
        if not MIGRATIONS_DIR.exists():
            return
        async with self._pool.acquire() as conn:
            await conn.execute("SELECT pg_advisory_lock($1)", 54912047)
            try:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        name TEXT PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )
                rows = await conn.fetch("SELECT name FROM schema_migrations")
                applied = {row["name"] for row in rows}
                for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                    if path.name in applied:
                        continue
                    sql = path.read_text(encoding="utf-8")
                    async with conn.transaction():
                        await conn.execute(sql)
                        await conn.execute(
                            "INSERT INTO schema_migrations (name) VALUES ($1)",
                            path.name,
                        )
            finally:
                await conn.execute("SELECT pg_advisory_unlock($1)", 54912047)

    async def ensure_settings_defaults(self, defaults: dict[str, str | None]) -> None:
        await self.connect()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for key, value in defaults.items():
                    await conn.execute(
                        """
                        INSERT INTO bot_settings (key, value)
                        VALUES ($1, $2)
                        ON CONFLICT (key) DO NOTHING
                        """,
                        key,
                        value,
                    )

    async def fetch_settings(self) -> dict[str, str | None]:
        await self.connect()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT key, value FROM bot_settings")
            return {row["key"]: row["value"] for row in rows}

    async def set_setting(self, key: str, value: str | None) -> None:
        await self.connect()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bot_settings (key, value, updated_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (key)
                DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """,
                key,
                value,
            )

    async def upsert_user(
        self,
        *,
        telegram_id: int,
        first_name: str | None,
        last_name: str | None,
        username: str | None,
        language_code: str | None,
        is_bot: bool,
    ) -> None:
        await self.connect()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users (
                    telegram_id,
                    first_name,
                    last_name,
                    username,
                    language_code,
                    is_bot,
                    first_seen,
                    last_seen,
                    created_at,
                    updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW(), NOW(), NOW())
                ON CONFLICT (telegram_id) DO UPDATE
                SET
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    username = EXCLUDED.username,
                    language_code = EXCLUDED.language_code,
                    is_bot = EXCLUDED.is_bot,
                    last_seen = NOW(),
                    updated_at = NOW()
                """,
                telegram_id,
                first_name,
                last_name,
                username,
                language_code,
                is_bot,
            )

    async def get_user_count(self) -> int:
        await self.connect()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT COUNT(*) AS count FROM users")
            return int(row["count"] if row else 0)

    async def list_users(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        await self.connect()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id,
                    telegram_id,
                    first_name,
                    last_name,
                    username,
                    language_code,
                    is_bot,
                    first_seen,
                    last_seen,
                    created_at,
                    updated_at
                FROM users
                ORDER BY last_seen DESC, telegram_id DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
            return [dict(row) for row in rows]

    async def get_user_by_telegram_id(self, telegram_id: int) -> dict[str, Any] | None:
        await self.connect()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    id,
                    telegram_id,
                    first_name,
                    last_name,
                    username,
                    language_code,
                    is_bot,
                    first_seen,
                    last_seen,
                    created_at,
                    updated_at
                FROM users
                WHERE telegram_id = $1
                """,
                telegram_id,
            )
            return dict(row) if row else None

    async def create_conversation(
        self,
        *,
        telegram_id: int,
        title: str | None = None,
    ) -> int:
        await self.connect()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO conversations (telegram_id, title)
                VALUES ($1, $2)
                RETURNING id
                """,
                telegram_id,
                title,
            )
            return int(row["id"])

    async def get_conversation(
        self,
        *,
        telegram_id: int,
        conversation_id: int,
        include_deleted: bool = False,
    ) -> dict[str, Any] | None:
        await self.connect()
        clause = "" if include_deleted else "AND deleted_at IS NULL"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT
                    id,
                    telegram_id,
                    title,
                    created_at,
                    updated_at,
                    deleted_at
                FROM conversations
                WHERE id = $1 AND telegram_id = $2 {clause}
                """,
                conversation_id,
                telegram_id,
            )
            return dict(row) if row else None

    async def get_conversation_by_id(
        self,
        conversation_id: int,
    ) -> dict[str, Any] | None:
        await self.connect()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    id,
                    telegram_id,
                    title,
                    created_at,
                    updated_at,
                    deleted_at
                FROM conversations
                WHERE id = $1
                """,
                conversation_id,
            )
            return dict(row) if row else None

    async def count_conversations(
        self,
        *,
        telegram_id: int,
        include_deleted: bool = False,
    ) -> int:
        await self.connect()
        clause = "" if include_deleted else "AND deleted_at IS NULL"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT COUNT(*) AS count
                FROM conversations
                WHERE telegram_id = $1 {clause}
                """,
                telegram_id,
            )
            return int(row["count"] if row else 0)

    async def list_conversations(
        self,
        *,
        telegram_id: int,
        include_deleted: bool = False,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        await self.connect()
        clause = "" if include_deleted else "AND deleted_at IS NULL"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT
                    id,
                    telegram_id,
                    title,
                    created_at,
                    updated_at,
                    deleted_at
                FROM conversations
                WHERE telegram_id = $1 {clause}
                ORDER BY updated_at DESC, id DESC
                LIMIT $2 OFFSET $3
                """,
                telegram_id,
                limit,
                offset,
            )
            return [dict(row) for row in rows]

    async def list_conversations_with_last_message(
        self,
        *,
        telegram_id: int,
        include_deleted: bool = False,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        await self.connect()
        clause = "" if include_deleted else "AND c.deleted_at IS NULL"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT
                    c.id,
                    c.telegram_id,
                    c.title,
                    c.created_at,
                    c.updated_at,
                    c.deleted_at,
                    lm.role AS last_role,
                    lm.is_error AS last_is_error,
                    lm.created_at AS last_message_at
                FROM conversations c
                LEFT JOIN LATERAL (
                    SELECT role, is_error, created_at
                    FROM messages m
                    WHERE m.conversation_id = c.id
                    ORDER BY m.created_at DESC, m.id DESC
                    LIMIT 1
                ) lm ON true
                WHERE c.telegram_id = $1 {clause}
                ORDER BY c.updated_at DESC, c.id DESC
                LIMIT $2 OFFSET $3
                """,
                telegram_id,
                limit,
                offset,
            )
            return [dict(row) for row in rows]

    async def soft_delete_conversation(
        self,
        *,
        telegram_id: int,
        conversation_id: int,
    ) -> None:
        await self.connect()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE conversations
                SET deleted_at = NOW(), updated_at = NOW()
                WHERE id = $1 AND telegram_id = $2 AND deleted_at IS NULL
                """,
                conversation_id,
                telegram_id,
            )

    async def update_conversation_title(
        self,
        *,
        conversation_id: int,
        title: str,
    ) -> None:
        await self.connect()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE conversations
                SET title = $1, updated_at = NOW()
                WHERE id = $2 AND (title IS NULL OR title = '')
                """,
                title,
                conversation_id,
            )

    async def count_messages(self, *, conversation_id: int) -> int:
        await self.connect()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS count FROM messages WHERE conversation_id = $1",
                conversation_id,
            )
            return int(row["count"] if row else 0)

    async def list_messages(
        self,
        *,
        conversation_id: int,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        await self.connect()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id,
                    role,
                    content,
                    is_error,
                    model,
                    created_at
                FROM messages
                WHERE conversation_id = $1
                ORDER BY created_at ASC, id ASC
                LIMIT $2 OFFSET $3
                """,
                conversation_id,
                limit,
                offset,
            )
            return [dict(row) for row in rows]

    async def insert_message(
        self,
        *,
        conversation_id: int,
        role: str,
        content: str,
        is_error: bool = False,
        model: str | None = None,
    ) -> None:
        await self.connect()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO messages (conversation_id, role, content, is_error, model)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    conversation_id,
                    role,
                    content,
                    is_error,
                    model,
                )
                await conn.execute(
                    "UPDATE conversations SET updated_at = NOW() WHERE id = $1",
                    conversation_id,
                )

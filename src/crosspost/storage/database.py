import json
from pathlib import Path

import aiosqlite

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vk_group_id INTEGER NOT NULL,
    vk_post_id INTEGER NOT NULL,
    owner_id INTEGER NOT NULL,
    post_date INTEGER NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (vk_group_id, vk_post_id)
);

CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    original_url TEXT,
    raw_json TEXT NOT NULL,

    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
    UNIQUE (post_id, position)
);

CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    remote_message_id TEXT,
    error TEXT,
    outcome_uncertain INTEGER NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,

    UNIQUE (post_id, platform),

    CHECK (platform IN ('telegram', 'max')),
    CHECK (status IN ('pending', 'processing', 'published', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_deliveries_status
ON deliveries(platform, status);

CREATE INDEX IF NOT EXISTS idx_posts_date
ON posts(post_date);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self._connection = await aiosqlite.connect(self.path)
        self._connection.row_factory = aiosqlite.Row

        await self._connection.execute("PRAGMA foreign_keys = ON")
        await self._connection.execute("PRAGMA journal_mode = WAL")
        await self._connection.execute("PRAGMA busy_timeout = 5000")

    async def initialize(self) -> None:
        connection = self._require_connection()
        await connection.executescript(SCHEMA)
        await connection.commit()

    async def save_post(self, post: dict) -> bool:
        """
        Сохраняет пост, вложения и delivery для Telegram и MAX
        в одной транзакции.

        Возвращает:
            True  — новая публикация сохранена;
            False — такая публикация уже есть.
        """
        connection = self._require_connection()

        await connection.execute("BEGIN IMMEDIATE")

        try:
            cursor = await connection.execute(
                """
                INSERT INTO posts (
                    vk_group_id,
                    vk_post_id,
                    owner_id,
                    post_date,
                    text,
                    source_url,
                    raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(vk_group_id, vk_post_id) DO NOTHING
                """,
                (
                    post["vk_group_id"],
                    post["vk_post_id"],
                    post["owner_id"],
                    post["post_date"],
                    post.get("text", ""),
                    post["source_url"],
                    json.dumps(post["raw_json"], ensure_ascii=False),
                ),
            )

            if cursor.rowcount == 0:
                await connection.rollback()
                return False

            post_id = cursor.lastrowid
            await cursor.close()

            for position, attachment in enumerate(post.get("media", [])):
                await connection.execute(
                    """
                    INSERT INTO media (
                        post_id,
                        position,
                        media_type,
                        original_url,
                        raw_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        post_id,
                        position,
                        attachment["media_type"],
                        attachment.get("original_url"),
                        json.dumps(
                            attachment["raw_json"],
                            ensure_ascii=False,
                        ),
                    ),
                )

            for platform in ("telegram", "max"):
                await connection.execute(
                    """
                    INSERT INTO deliveries (post_id, platform)
                    VALUES (?, ?)
                    """,
                    (post_id, platform),
                )

            await connection.commit()
            return True

        except Exception:
            await connection.rollback()
            raise

    async def claim_next_telegram_delivery(self) -> dict | None:
        """
        Атомарно захватывает самое старое ожидающее задание Telegram.

        Возвращает delivery, post и media либо None.
        """
        connection = self._require_connection()

        await connection.execute("BEGIN IMMEDIATE")

        try:
            cursor = await connection.execute(
                """
                SELECT
                    d.id AS delivery_id,
                    d.post_id,
                    d.platform,
                    d.status,
                    p.vk_group_id,
                    p.vk_post_id,
                    p.owner_id,
                    p.post_date,
                    p.text,
                    p.source_url,
                    p.raw_json
                FROM deliveries AS d
                JOIN posts AS p ON p.id = d.post_id
                WHERE d.platform = 'telegram'
                  AND d.status = 'pending'
                  AND d.outcome_uncertain = 0
                  AND d.needs_review = 0
                ORDER BY p.post_date ASC, d.id ASC
                LIMIT 1
                """
            )

            row = await cursor.fetchone()
            await cursor.close()

            if row is None:
                await connection.commit()
                return None

            delivery_id = row["delivery_id"]
            post_id = row["post_id"]

            update_cursor = await connection.execute(
                """
                UPDATE deliveries
                SET status = 'processing',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND status = 'pending'
                """,
                (delivery_id,),
            )

            if update_cursor.rowcount != 1:
                await update_cursor.close()
                await connection.rollback()
                return None

            await update_cursor.close()

            media_cursor = await connection.execute(
                """
                SELECT
                    id,
                    position,
                    media_type,
                    original_url,
                    raw_json
                FROM media
                WHERE post_id = ?
                ORDER BY position ASC
                """,
                (post_id,),
            )

            media_rows = await media_cursor.fetchall()
            await media_cursor.close()

            await connection.commit()

            delivery = {
                "id": delivery_id,
                "post_id": post_id,
                "platform": row["platform"],
                "status": "processing",
            }

            post = {
                "id": post_id,
                "vk_group_id": row["vk_group_id"],
                "vk_post_id": row["vk_post_id"],
                "owner_id": row["owner_id"],
                "post_date": row["post_date"],
                "text": row["text"],
                "source_url": row["source_url"],
                "raw_json": json.loads(row["raw_json"]),
            }

            media = [
                {
                    "id": item["id"],
                    "position": item["position"],
                    "media_type": item["media_type"],
                    "original_url": item["original_url"],
                    "raw_json": json.loads(item["raw_json"]),
                }
                for item in media_rows
            ]

            return {
                "delivery": delivery,
                "post": post,
                "media": media,
            }

        except Exception:
            await connection.rollback()
            raise

    async def mark_delivery_published(
        self,
        delivery_id: int,
        remote_message_id: str,
    ) -> None:
        connection = self._require_connection()

        cursor = await connection.execute(
            """
            UPDATE deliveries
            SET status = 'published',
                remote_message_id = ?,
                error = NULL,
                outcome_uncertain = 0,
                needs_review = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND platform = 'telegram'
              AND status = 'processing'
            """,
            (remote_message_id, delivery_id),
        )

        await connection.commit()

        if cursor.rowcount != 1:
            await cursor.close()
            raise RuntimeError(f"Cannot mark Telegram delivery {delivery_id} as published")

        await cursor.close()

    async def mark_delivery_failed(
        self,
        delivery_id: int,
        error: str,
    ) -> None:
        connection = self._require_connection()

        cursor = await connection.execute(
            """
            UPDATE deliveries
            SET status = 'failed',
                error = ?,
                outcome_uncertain = 0,
                needs_review = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND platform = 'telegram'
              AND status = 'processing'
            """,
            (error, delivery_id),
        )

        await connection.commit()

        if cursor.rowcount != 1:
            await cursor.close()
            raise RuntimeError(f"Cannot mark Telegram delivery {delivery_id} as failed")

        await cursor.close()

    async def mark_delivery_uncertain(
        self,
        delivery_id: int,
        error: str,
    ) -> None:
        connection = self._require_connection()

        cursor = await connection.execute(
            """
            UPDATE deliveries
            SET error = ?,
                outcome_uncertain = 1,
                needs_review = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND platform = 'telegram'
              AND status = 'processing'
            """,
            (error, delivery_id),
        )

        await connection.commit()

        if cursor.rowcount != 1:
            await cursor.close()
            raise RuntimeError(f"Cannot mark Telegram delivery {delivery_id} as uncertain")

        await cursor.close()

    async def recover_interrupted_deliveries(self) -> int:
        """
        Помечает оставшиеся processing-задания Telegram
        как требующие ручной проверки.

        Возвращает количество новых обнаруженных заданий.
        """
        connection = self._require_connection()

        cursor = await connection.execute(
            """
            UPDATE deliveries
            SET error = 'Application stopped during Telegram delivery',
                outcome_uncertain = 1,
                needs_review = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE platform = 'telegram'
            AND status = 'processing'
            AND outcome_uncertain = 0
            AND needs_review = 0
            """
        )

        await connection.commit()

        count = cursor.rowcount
        await cursor.close()

        return count

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    def _require_connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("Database is not connected")
        return self._connection

    async def __aenter__(self) -> "Database":
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

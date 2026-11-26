"""Состояние Telegram-доставок. Только чтение, ничего не публикует.

uv run python scripts/telegram/show_deliveries.py
uv run python scripts/telegram/show_deliveries.py --platform max
"""

import argparse
import asyncio
import logging
from pathlib import Path

from crosspost.storage.database import Database

PROJECT_ROOT = Path(__file__).resolve().parents[2]

logger = logging.getLogger("crosspost.scripts.show_deliveries")

QUERY = """
SELECT
    d.id AS delivery_id,
    d.platform,
    p.vk_post_id,
    p.post_date,
    d.status,
    d.remote_message_id,
    d.outcome_uncertain,
    d.needs_review,
    d.error,
    length(p.text) AS text_length,
    (
        SELECT COUNT(*) FROM media AS m
        WHERE m.post_id = p.id
          AND m.media_type = 'photo'
          AND m.original_url IS NOT NULL
    ) AS photos,
    (
        SELECT COUNT(*) FROM media AS m
        WHERE m.post_id = p.id
          AND m.media_type = 'video'
          AND m.original_url IS NOT NULL
    ) AS videos_with_url,
    (
        SELECT COUNT(*) FROM media AS m
        WHERE m.post_id = p.id
          AND m.media_type = 'video'
          AND m.original_url IS NULL
    ) AS videos_without_url,
    (
        SELECT COUNT(*) FROM media AS m
        WHERE m.post_id = p.id
          AND m.media_type = 'link'
          AND m.original_url IS NOT NULL
    ) AS links
FROM deliveries AS d
JOIN posts AS p ON p.id = d.post_id
WHERE d.platform = ?
ORDER BY p.post_date ASC, d.id ASC
"""


async def show(database: Database, platform: str) -> int:
    connection = database._require_connection()

    cursor = await connection.execute(QUERY, (platform,))
    rows = await cursor.fetchall()
    await cursor.close()

    if not rows:
        logger.info("Доставок для платформы %s нет", platform)
        return 0

    for row in rows:
        logger.info(
            "delivery=%s vk_post=%s date=%s status=%s id=%s "
            "uncertain=%s review=%s text=%s photo=%s "
            "video_url=%s video_no_url=%s link=%s error=%s",
            row["delivery_id"],
            row["vk_post_id"],
            row["post_date"],
            row["status"],
            row["remote_message_id"],
            row["outcome_uncertain"],
            row["needs_review"],
            row["text_length"],
            row["photos"],
            row["videos_with_url"],
            row["videos_without_url"],
            row["links"],
            row["error"],
        )

    summary: dict[str, int] = {}
    for row in rows:
        summary[row["status"]] = summary.get(row["status"], 0) + 1

    logger.info("Всего доставок %s: %s", platform, len(rows))
    logger.info("По статусам: %s", summary)

    without_url = sum(row["videos_without_url"] for row in rows)
    logger.info("Видео без original_url во всех постах: %s", without_url)

    return len(rows)


async def run(args: argparse.Namespace) -> int:
    database = Database(args.db)
    await database.connect()

    try:
        return await show(database, args.platform)
    finally:
        await database.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Показать состояние доставок",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=PROJECT_ROOT / "data" / "crosspost.db",
    )
    parser.add_argument(
        "--platform",
        choices=("telegram", "max"),
        default="telegram",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

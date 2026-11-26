"""Диагностический запуск Telegram worker на реальной БД и реальном канале.

Публикует ожидающие Telegram-доставки. MAX-доставки не затрагиваются.
Не является production-точкой входа.

    uv run python scripts/telegram/run_worker.py --preview
    uv run python scripts/telegram/run_worker.py --recover --limit 1
"""

import argparse
import asyncio
import logging
from pathlib import Path

import httpx
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from crosspost.config import settings
from crosspost.storage.database import Database
from crosspost.telegram.publisher import TelegramPublisher
from crosspost.telegram.worker import TelegramWorker
from crosspost.vk.media import MediaDownloader

PROJECT_ROOT = Path(__file__).resolve().parents[2]

logger = logging.getLogger("crosspost.scripts.telegram_worker")


async def print_preview(database: Database) -> int:
    """Показывает очередь Telegram, не изменяя статусы доставок."""
    connection = database._require_connection()

    cursor = await connection.execute(
        """
        SELECT
            d.id AS delivery_id,
            p.vk_post_id,
            p.post_date,
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
            ) AS videos,
            (
                SELECT COUNT(*) FROM media AS m
                WHERE m.post_id = p.id
                  AND m.media_type = 'link'
                  AND m.original_url IS NOT NULL
            ) AS links
        FROM deliveries AS d
        JOIN posts AS p ON p.id = d.post_id
        WHERE d.platform = 'telegram'
          AND d.status = 'pending'
          AND d.outcome_uncertain = 0
          AND d.needs_review = 0
        ORDER BY p.post_date ASC, d.id ASC
        """
    )

    rows = await cursor.fetchall()
    await cursor.close()

    if not rows:
        logger.info("Очередь Telegram пуста")
        return 0

    for row in rows:
        logger.info(
            "delivery=%s vk_post=%s post_date=%s text=%s photo=%s video=%s link=%s",
            row["delivery_id"],
            row["vk_post_id"],
            row["post_date"],
            row["text_length"],
            row["photos"],
            row["videos"],
            row["links"],
        )

    logger.info("Ожидает обработки доставок: %s", len(rows))

    return len(rows)


async def publish(args: argparse.Namespace, database: Database) -> int:
    """Публикует доставки по одной, максимум args.limit штук."""
    session = AiohttpSession(timeout=settings.upload_timeout_seconds)
    bot = Bot(
        token=settings.tg_bot_token.get_secret_value(),
        session=session,
    )

    processed = 0

    try:
        async with httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
        ) as client:
            worker = TelegramWorker(
                database=database,
                publisher=TelegramPublisher(bot, settings.tg_chat_id),
                downloader=MediaDownloader(client),
                work_dir=args.work_dir,
            )

            while processed < args.limit:
                if not await worker.process_next():
                    logger.info("Очередь Telegram пуста")
                    break

                processed += 1
                logger.info("Обработано доставок: %s", processed)

    finally:
        await session.close()

    logger.info("Итог запуска: обработано доставок %s", processed)

    return 0


async def run(args: argparse.Namespace) -> int:
    database = Database(args.db)
    await database.connect()

    try:
        if args.recover:
            recovered = await database.recover_interrupted_deliveries()
            logger.info("recover_interrupted_deliveries: помечено %s", recovered)

        if args.preview:
            return await print_preview(database)

        return await publish(args, database)

    finally:
        await database.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Запуск Telegram worker на реальной БД",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=PROJECT_ROOT / "data" / "crosspost.db",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "media_staging",
        help=(
            "каталог для скачанных фото; worker удаляет их "
            "после публикации, поэтому не указывать media/vk"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="максимальное число доставок за один запуск",
    )
    parser.add_argument(
        "--recover",
        action="store_true",
        help="пометить незавершённые processing-доставки как неопределённые",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="только показать очередь, ничего не публиковать",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    ignored = ("httpx", "aiogram", "aiohttp")
    for name in ignored:
        logging.getLogger(name).setLevel(logging.WARNING)

    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

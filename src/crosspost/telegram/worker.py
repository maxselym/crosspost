"""Обработчик очереди Telegram-доставок."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlparse

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramConflictError,
    TelegramEntityTooLarge,
    TelegramForbiddenError,
    TelegramMigrateToChat,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramUnauthorizedError,
)

from crosspost.storage.database import Database
from crosspost.telegram.publisher import TelegramPublisher
from crosspost.vk.media import MediaDownloader

logger = logging.getLogger(__name__)

TELEGRAM_MESSAGE_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024
ALBUM_MIN_SIZE = 2
ALBUM_MAX_SIZE = 10

PHOTO_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})

NOTHING_TO_PUBLISH = "nothing_to_publish: post has neither text nor publishable media"
# Ошибки Telegram, при которых сообщение заведомо не было опубликовано.
# TelegramNetworkError, TelegramServerError, таймауты и любые неизвестные
# исключения сюда сознательно не входят: их исход неизвестен, поэтому
# в _is_definite_error() они дают False и доставка помечается как uncertain.
DEFINITE_TELEGRAM_ERRORS = (
    TelegramBadRequest,
    TelegramUnauthorizedError,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramMigrateToChat,
    TelegramConflictError,
    TelegramEntityTooLarge,
    TelegramRetryAfter,
)


class NothingToPublishError(Exception):
    """Пост не содержит ни текста, ни пригодных для публикации медиа."""


class DeliveryPreparationError(Exception):
    """Не удалось подготовить локальные файлы до обращения к Telegram."""


class TelegramWorker:
    """Публикует посты в Telegram, связывая Database и TelegramPublisher.

    Все внешние объекты внедряются: Worker не создаёт Bot, Database,
    httpx.AsyncClient и загрузчик медиа.

    Неопределённый исход отправки (outcome_uncertain) никогда не повторяется
    автоматически: такие доставки не выбираются claim_next_telegram_delivery().
    """

    def __init__(
        self,
        database: Database,
        publisher: TelegramPublisher,
        downloader: MediaDownloader,
        work_dir: Path,
        *,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        self._database = database
        self._publisher = publisher
        self._downloader = downloader
        self._work_dir = Path(work_dir)
        self._poll_interval_seconds = poll_interval_seconds

    async def process_next(self) -> bool:
        """Обрабатывает одну доставку.

        Возвращает True, если доставка была захвачена и обработана
        (независимо от её итогового статуса), и False, если очередь пуста.
        """
        claimed = await self._database.claim_next_telegram_delivery()

        if claimed is None:
            return False

        await self._handle(claimed)
        return True

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        """Обрабатывает очередь до установки stop_event или отмены задачи."""
        stop_event = stop_event or asyncio.Event()

        while not stop_event.is_set():
            if await self.process_next():
                continue

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self._poll_interval_seconds,
                )
            except TimeoutError:
                continue

    async def _handle(self, claimed: dict) -> None:
        delivery_id: int = claimed["delivery"]["id"]
        post: dict = claimed["post"]
        media: list[dict] = claimed["media"]

        sent_ids: list[int] = []
        temp_paths: list[Path] = []

        try:
            await self._deliver(post, media, sent_ids, temp_paths)
        except asyncio.CancelledError:
            # Отмена во время публикации: сообщение могло уйти.
            await self._mark_uncertain(
                delivery_id,
                "Worker cancelled during Telegram publication",
            )
            raise
        except NothingToPublishError as error:
            await self._mark_failed(delivery_id, str(error))
        except Exception as error:
            await self._record_failure(delivery_id, error, sent_ids)
        else:
            await self._mark_published(delivery_id, sent_ids)
        finally:
            self._remove_files(temp_paths)

    async def _deliver(
        self,
        post: dict,
        media: list[dict],
        sent_ids: list[int],
        temp_paths: list[Path],
    ) -> None:
        text = (post.get("text") or "").strip()
        photo_urls, video_urls, link_urls = _collect_media(media)
        body = _compose_body(text, video_urls, link_urls)

        photo_paths = await self._download_photos(
            post_id=post["id"],
            urls=photo_urls,
            temp_paths=temp_paths,
        )

        if not body and not photo_paths:
            raise NothingToPublishError(NOTHING_TO_PUBLISH)

        caption: str | None = None
        pending_text = body

        if photo_paths and len(body) <= TELEGRAM_CAPTION_LIMIT:
            caption = body or None
            pending_text = ""

        # Текст публикуется первым, чтобы подпись не дублировала его.
        if pending_text:
            for chunk in _split_text(pending_text, TELEGRAM_MESSAGE_LIMIT):
                message = await self._publisher.publish_text(
                    chunk,
                    parse_mode=None,
                )
                sent_ids.append(message.message_id)

        # Подпись несёт только первый блок фотографий.
        for group in _chunk(photo_paths, ALBUM_MAX_SIZE):
            if len(group) == 1:
                message = await self._publisher.publish_photo(
                    group[0],
                    caption=caption,
                    parse_mode=None,
                )
                sent_ids.append(message.message_id)
            else:
                messages = await self._publisher.publish_album(
                    group,
                    caption=caption,
                    parse_mode=None,
                )
                sent_ids.extend(message.message_id for message in messages)

            caption = None

        if not sent_ids:
            raise NothingToPublishError(NOTHING_TO_PUBLISH)

    async def _download_photos(
        self,
        post_id: int,
        urls: list[str],
        temp_paths: list[Path],
    ) -> list[Path]:
        paths: list[Path] = []

        for index, url in enumerate(urls):
            destination = self._work_dir / _photo_file_name(post_id, index, url)

            try:
                await self._downloader.download(url, destination)
            except Exception as error:
                raise DeliveryPreparationError(f"Failed to download {url}: {error}") from error

            temp_paths.append(destination)
            paths.append(destination)

        return paths

    async def _record_failure(
        self,
        delivery_id: int,
        error: BaseException,
        sent_ids: list[int],
    ) -> None:
        message = f"{type(error).__name__}: {error}"

        if sent_ids:
            sent = ", ".join(str(item) for item in sent_ids)
            await self._mark_uncertain(
                delivery_id,
                f"{message} (already sent message ids: {sent})",
            )
            return

        if self._is_definite_error(error):
            await self._mark_failed(delivery_id, message)
        else:
            await self._mark_uncertain(delivery_id, message)

    @staticmethod
    def _is_definite_error(error: BaseException) -> bool:
        if isinstance(error, (NothingToPublishError, DeliveryPreparationError)):
            return True
        return isinstance(error, DEFINITE_TELEGRAM_ERRORS)

    async def _mark_published(
        self,
        delivery_id: int,
        sent_ids: list[int],
    ) -> None:
        try:
            await self._database.mark_delivery_published(
                delivery_id,
                _format_message_ids(sent_ids),
            )
        except Exception:
            logger.exception("Cannot mark delivery %s as published", delivery_id)

    async def _mark_failed(self, delivery_id: int, message: str) -> None:
        try:
            await self._database.mark_delivery_failed(delivery_id, message)
        except Exception:
            logger.exception("Cannot mark delivery %s as failed", delivery_id)

    async def _mark_uncertain(self, delivery_id: int, message: str) -> None:
        try:
            await self._database.mark_delivery_uncertain(delivery_id, message)
        except Exception:
            logger.exception("Cannot mark delivery %s as uncertain", delivery_id)

    @staticmethod
    def _remove_files(paths: list[Path]) -> None:
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Cannot remove temporary file %s", path)


def _collect_media(
    media: list[dict],
) -> tuple[list[str], list[str], list[str]]:
    """Разбирает media по position, отбрасывая записи без URL."""
    photo_urls: list[str] = []
    video_urls: list[str] = []
    link_urls: list[str] = []

    for item in media:
        media_type = item.get("media_type")
        url = item.get("original_url")

        if not url:
            logger.debug(
                "Skip media %s without url",
                item.get("id"),
            )
            continue

        if media_type == "photo":
            photo_urls.append(url)
        elif media_type == "video":
            _append_unique(video_urls, url)
        elif media_type == "link":
            _append_unique(link_urls, url)

    return photo_urls, video_urls, link_urls


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _compose_body(text: str, video_urls: list[str], link_urls: list[str]) -> str:
    parts: list[str] = []

    if text:
        parts.append(text)
    if video_urls:
        parts.append("\n".join(f"Видео: {url}" for url in video_urls))
    if link_urls:
        parts.append("\n".join(link_urls))

    return "\n\n".join(parts)


def _split_text(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    remaining = text.strip()

    while len(remaining) > limit:
        window = remaining[:limit]

        cut = window.rfind("\n\n")
        if cut <= 0:
            cut = window.rfind("\n")
        if cut <= 0:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit

        head = remaining[:cut].strip()
        if head:
            chunks.append(head)

        remaining = remaining[cut:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


def _chunk(paths: list[Path], size: int) -> list[list[Path]]:
    return [paths[index : index + size] for index in range(0, len(paths), size)]


def _format_message_ids(message_ids: Sequence[int]) -> str:
    if len(message_ids) == 1:
        return str(message_ids[0])
    return json.dumps(list(message_ids))


def _photo_file_name(post_id: int, index: int, url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()

    if suffix not in PHOTO_SUFFIXES:
        suffix = ".jpg"

    return f"{post_id}_{index}{suffix}"

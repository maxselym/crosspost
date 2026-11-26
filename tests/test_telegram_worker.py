import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.methods import SendMessage

from crosspost.storage.database import Database
from crosspost.telegram.worker import TelegramWorker

VK_GROUP_ID = 227892646
OWNER_ID = -227892646


class FakePublisher:
    def __init__(self) -> None:
        self.text_messages: list[tuple[str, str | None]] = []
        self.photo_messages: list[tuple[Any, str | None, str | None]] = []
        self.album_messages: list[tuple[list, str | None, str | None]] = []
        self.errors: list[BaseException | None] = []
        self._next_message_id = 1000
        self.errors: list[BaseException | None] = []
        self.attempts = 0

    def _next_id(self) -> int:
        self._next_message_id += 1
        return self._next_message_id

    def _register_attempt(self) -> None:
        self.attempts += 1

        if not self.errors:
            return

        error = self.errors.pop(0)
        if error is not None:
            raise error

    async def publish_text(
        self,
        text: str,
        *,
        parse_mode: str | None = "HTML",
    ) -> Any:
        self._register_attempt()
        self.text_messages.append((text, parse_mode))
        return SimpleNamespace(message_id=self._next_id())

    async def publish_photo(
        self,
        photo: Any,
        *,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
    ) -> Any:
        self._register_attempt()
        self.photo_messages.append((photo, caption, parse_mode))
        return SimpleNamespace(message_id=self._next_id())

    async def publish_album(
        self,
        photos: list,
        *,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
    ) -> list[Any]:
        self._register_attempt()
        self.album_messages.append((list(photos), caption, parse_mode))
        return [SimpleNamespace(message_id=self._next_id()) for _ in photos]


class FakeDownloader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []
        self.error: Exception | None = None

    async def download(self, url: str, destination: Path) -> Path:
        if self.error is not None:
            raise self.error

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"photo-bytes")
        self.calls.append((url, destination))
        return destination


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "worker.db")
    await db.connect()
    await db.initialize()

    yield db

    await db.close()


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def downloader() -> FakeDownloader:
    return FakeDownloader()


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    return tmp_path / "work"


def make_worker(
    database: Database,
    publisher: FakePublisher,
    downloader: FakeDownloader,
    work_dir: Path,
) -> TelegramWorker:
    return TelegramWorker(
        database=database,
        publisher=publisher,
        downloader=downloader,
        work_dir=work_dir,
    )


async def add_post(
    database: Database,
    vk_post_id: int,
    *,
    text: str = "",
    media: list[dict] | None = None,
) -> None:
    await database.save_post(
        {
            "vk_group_id": VK_GROUP_ID,
            "vk_post_id": vk_post_id,
            "owner_id": OWNER_ID,
            "post_date": 100 + vk_post_id,
            "text": text,
            "source_url": f"https://vk.com/wall{OWNER_ID}_{vk_post_id}",
            "raw_json": {"id": vk_post_id},
            "media": media or [],
        }
    )


def photo_attachment(position: int, url: str | None = None) -> dict:
    return {
        "media_type": "photo",
        "original_url": url or f"https://cdn.example.com/{position}.jpg",
        "raw_json": {"type": "photo", "position": position},
    }


def video_attachment(url: str) -> dict:
    return {
        "media_type": "video",
        "original_url": url,
        "raw_json": {"type": "video", "id": 1, "owner_id": OWNER_ID},
    }


def link_attachment(url: str) -> dict:
    return {
        "media_type": "link",
        "original_url": url,
        "raw_json": {"type": "link", "link": {"url": url}},
    }


async def get_telegram_delivery(database: Database, vk_post_id: int) -> dict:
    cursor = await database._require_connection().execute(
        """
        SELECT d.*
        FROM deliveries AS d
        JOIN posts AS p ON p.id = d.post_id
        WHERE p.vk_post_id = ? AND d.platform = 'telegram'
        """,
        (vk_post_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()

    return dict(row)


def network_error() -> TelegramNetworkError:
    return TelegramNetworkError(
        method=SendMessage(chat_id=-1004449971245, text="test"),
        message="Connection reset by peer",
    )


def bad_request() -> TelegramBadRequest:
    return TelegramBadRequest(
        method=SendMessage(chat_id=-1004449971245, text="test"),
        message="Bad Request: chat not found",
    )


@pytest.mark.asyncio
async def test_publishes_text_post(
    database: Database,
    publisher: FakePublisher,
    downloader: FakeDownloader,
    work_dir: Path,
) -> None:
    await add_post(database, 1, text="Привет <мир> & все")
    worker = make_worker(database, publisher, downloader, work_dir)

    assert await worker.process_next() is True

    assert publisher.text_messages == [("Привет <мир> & все", None)]
    assert publisher.photo_messages == []
    assert publisher.album_messages == []
    assert downloader.calls == []

    delivery = await get_telegram_delivery(database, 1)

    assert delivery["status"] == "published"
    assert delivery["remote_message_id"] == "1001"
    assert delivery["error"] is None
    assert delivery["outcome_uncertain"] == 0
    assert delivery["needs_review"] == 0


@pytest.mark.asyncio
async def test_publishes_single_photo_with_caption(
    database: Database,
    publisher: FakePublisher,
    downloader: FakeDownloader,
    work_dir: Path,
) -> None:
    await add_post(
        database,
        2,
        text="Подпись",
        media=[photo_attachment(0)],
    )
    worker = make_worker(database, publisher, downloader, work_dir)

    assert await worker.process_next() is True

    assert len(publisher.photo_messages) == 1
    photo_path, caption, parse_mode = publisher.photo_messages[0]

    assert Path(photo_path).name == "1_0.jpg"
    assert caption == "Подпись"
    assert parse_mode is None
    assert publisher.text_messages == []
    assert publisher.album_messages == []
    assert len(downloader.calls) == 1

    delivery = await get_telegram_delivery(database, 2)

    assert delivery["status"] == "published"
    assert delivery["remote_message_id"] == "1001"


@pytest.mark.asyncio
async def test_publishes_album_and_stores_all_ids(
    database: Database,
    publisher: FakePublisher,
    downloader: FakeDownloader,
    work_dir: Path,
) -> None:
    await add_post(
        database,
        3,
        text="Альбом",
        media=[
            photo_attachment(0),
            photo_attachment(1),
            photo_attachment(2),
        ],
    )
    worker = make_worker(database, publisher, downloader, work_dir)

    assert await worker.process_next() is True

    assert len(publisher.album_messages) == 1
    photos, caption, parse_mode = publisher.album_messages[0]

    assert len(photos) == 3
    assert caption == "Альбом"
    assert parse_mode is None
    assert publisher.photo_messages == []
    assert publisher.text_messages == []

    delivery = await get_telegram_delivery(database, 3)
    stored = delivery["remote_message_id"]

    assert delivery["status"] == "published"
    assert json.loads(stored) == [1001, 1002, 1003]


@pytest.mark.asyncio
async def test_empty_queue_returns_false(
    database: Database,
    publisher: FakePublisher,
    downloader: FakeDownloader,
    work_dir: Path,
) -> None:
    worker = make_worker(database, publisher, downloader, work_dir)

    assert await worker.process_next() is False
    assert publisher.text_messages == []
    assert publisher.photo_messages == []
    assert publisher.album_messages == []
    assert downloader.calls == []


@pytest.mark.asyncio
async def test_definite_error_marks_failed(
    database: Database,
    publisher: FakePublisher,
    downloader: FakeDownloader,
    work_dir: Path,
) -> None:
    await add_post(database, 5, text="Текст")
    publisher.errors = [bad_request()]
    worker = make_worker(database, publisher, downloader, work_dir)

    assert await worker.process_next() is True

    delivery = await get_telegram_delivery(database, 5)

    assert delivery["status"] == "failed"
    assert "TelegramBadRequest" in delivery["error"]
    assert delivery["remote_message_id"] is None
    assert delivery["outcome_uncertain"] == 0
    assert delivery["needs_review"] == 0


@pytest.mark.asyncio
async def test_network_error_marks_uncertain(
    database: Database,
    publisher: FakePublisher,
    downloader: FakeDownloader,
    work_dir: Path,
) -> None:
    await add_post(database, 6, text="Текст")
    publisher.errors = [network_error()]
    worker = make_worker(database, publisher, downloader, work_dir)

    assert await worker.process_next() is True

    delivery = await get_telegram_delivery(database, 6)

    assert delivery["status"] == "processing"
    assert delivery["outcome_uncertain"] == 1
    assert delivery["needs_review"] == 1
    assert "TelegramNetworkError" in delivery["error"]


@pytest.mark.asyncio
async def test_uncertain_delivery_is_not_retried(
    database: Database,
    publisher: FakePublisher,
    downloader: FakeDownloader,
    work_dir: Path,
) -> None:
    await add_post(database, 7, text="Текст")
    publisher.errors = [network_error()]
    worker = make_worker(database, publisher, downloader, work_dir)

    assert await worker.process_next() is True
    assert await worker.process_next() is False
    assert await worker.process_next() is False

    assert publisher.attempts == 1
    assert publisher.text_messages == []
    delivery = await get_telegram_delivery(database, 7)

    assert delivery["outcome_uncertain"] == 1
    assert delivery["needs_review"] == 1


@pytest.mark.asyncio
async def test_preparation_error_marks_failed(
    database: Database,
    publisher: FakePublisher,
    downloader: FakeDownloader,
    work_dir: Path,
) -> None:
    await add_post(
        database,
        9,
        text="Текст",
        media=[photo_attachment(0)],
    )
    downloader.error = OSError("disk is full")
    worker = make_worker(database, publisher, downloader, work_dir)

    assert await worker.process_next() is True

    assert publisher.text_messages == []
    assert publisher.photo_messages == []

    delivery = await get_telegram_delivery(database, 9)

    assert delivery["status"] == "failed"
    assert "DeliveryPreparationError" in delivery["error"]
    assert delivery["outcome_uncertain"] == 0


@pytest.mark.asyncio
async def test_temp_files_removed_after_success(
    database: Database,
    publisher: FakePublisher,
    downloader: FakeDownloader,
    work_dir: Path,
) -> None:
    await add_post(
        database,
        10,
        text="Текст",
        media=[photo_attachment(0), photo_attachment(1)],
    )
    worker = make_worker(database, publisher, downloader, work_dir)

    assert await worker.process_next() is True

    assert len(downloader.calls) == 2
    assert downloaded_files(work_dir) == []


@pytest.mark.asyncio
async def test_temp_files_removed_after_error(
    database: Database,
    publisher: FakePublisher,
    downloader: FakeDownloader,
    work_dir: Path,
) -> None:
    await add_post(
        database,
        11,
        text="Текст",
        media=[photo_attachment(0), photo_attachment(1)],
    )
    publisher.errors = [network_error()]
    worker = make_worker(database, publisher, downloader, work_dir)

    assert await worker.process_next() is True

    assert downloaded_files(work_dir) == []


@pytest.mark.asyncio
async def test_more_than_ten_photos_are_split(
    database: Database,
    publisher: FakePublisher,
    downloader: FakeDownloader,
    work_dir: Path,
) -> None:
    await add_post(
        database,
        12,
        media=[photo_attachment(position) for position in range(12)],
    )
    worker = make_worker(database, publisher, downloader, work_dir)

    assert await worker.process_next() is True

    assert len(publisher.album_messages) == 2

    first_photos, _, _ = publisher.album_messages[0]
    second_photos, _, _ = publisher.album_messages[1]

    assert len(first_photos) == 10
    assert len(second_photos) == 2
    assert publisher.photo_messages == []

    delivery = await get_telegram_delivery(database, 12)

    assert len(json.loads(delivery["remote_message_id"])) == 12


@pytest.mark.asyncio
async def test_long_text_is_sent_before_photos(
    database: Database,
    publisher: FakePublisher,
    downloader: FakeDownloader,
    work_dir: Path,
) -> None:
    long_text = "А" * 1500
    await add_post(
        database,
        13,
        text=long_text,
        media=[photo_attachment(0)],
    )
    worker = make_worker(database, publisher, downloader, work_dir)

    assert await worker.process_next() is True

    assert len(publisher.text_messages) == 1
    assert publisher.text_messages[0][0] == long_text
    assert publisher.text_messages[0][1] is None

    assert len(publisher.photo_messages) == 1
    assert publisher.photo_messages[0][1] is None

    delivery = await get_telegram_delivery(database, 13)

    assert json.loads(delivery["remote_message_id"]) == [1001, 1002]


@pytest.mark.asyncio
async def test_error_after_first_message_is_uncertain(
    database: Database,
    publisher: FakePublisher,
    downloader: FakeDownloader,
    work_dir: Path,
) -> None:
    await add_post(
        database,
        14,
        text="А" * 1500,
        media=[photo_attachment(0), photo_attachment(1)],
    )
    publisher.errors = [None, bad_request()]
    worker = make_worker(database, publisher, downloader, work_dir)

    assert await worker.process_next() is True

    delivery = await get_telegram_delivery(database, 14)

    assert delivery["status"] == "processing"
    assert delivery["outcome_uncertain"] == 1
    assert delivery["needs_review"] == 1
    assert "1001" in delivery["error"]


@pytest.mark.asyncio
async def test_post_without_publishable_content_marks_failed(
    database: Database,
    publisher: FakePublisher,
    downloader: FakeDownloader,
    work_dir: Path,
) -> None:
    await add_post(database, 15, text="   ")
    worker = make_worker(database, publisher, downloader, work_dir)

    assert await worker.process_next() is True

    assert publisher.text_messages == []

    delivery = await get_telegram_delivery(database, 15)

    assert delivery["status"] == "failed"
    assert "nothing_to_publish" in delivery["error"]
    assert delivery["outcome_uncertain"] == 0


@pytest.mark.asyncio
async def test_video_and_link_urls_are_published_as_text(
    database: Database,
    publisher: FakePublisher,
    downloader: FakeDownloader,
    work_dir: Path,
) -> None:
    video_url = "https://vk.com/video-227892646_456239081"
    link_url = "https://example.com/article"

    await add_post(
        database,
        16,
        text="Пост",
        media=[video_attachment(video_url), link_attachment(link_url)],
    )
    worker = make_worker(database, publisher, downloader, work_dir)

    assert await worker.process_next() is True

    assert downloader.calls == []
    assert len(publisher.text_messages) == 1

    text, parse_mode = publisher.text_messages[0]

    assert parse_mode is None
    assert "Пост" in text
    assert video_url in text
    assert link_url in text


def downloaded_files(work_dir: Path) -> list[Path]:
    if not work_dir.exists():
        return []
    return [path for path in work_dir.iterdir() if path.is_file()]

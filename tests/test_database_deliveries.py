import pytest
import pytest_asyncio

from crosspost.storage.database import Database


@pytest_asyncio.fixture
async def database(tmp_path):
    db = Database(tmp_path / "test_crosspost.db")
    await db.connect()
    await db.initialize()

    yield db

    await db.close()


async def add_post(db: Database, post_id: int, post_date: int) -> None:
    await db.save_post(
        {
            "vk_group_id": 227892646,
            "vk_post_id": post_id,
            "owner_id": -227892646,
            "post_date": post_date,
            "text": f"Test post {post_id}",
            "source_url": f"https://vk.com/wall-227892646_{post_id}",
            "raw_json": {"id": post_id},
            "media": [
                {
                    "media_type": "photo",
                    "original_url": f"https://example.com/{post_id}.jpg",
                    "raw_json": {"type": "photo", "id": post_id},
                }
            ],
        }
    )


async def get_delivery(db: Database, delivery_id: int) -> dict:
    cursor = await db._require_connection().execute(
        "SELECT * FROM deliveries WHERE id = ?",
        (delivery_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()

    return dict(row)


@pytest.mark.asyncio
async def test_claim_returns_oldest_pending_once(database: Database) -> None:
    await add_post(database, 101, 200)
    await add_post(database, 102, 100)

    first = await database.claim_next_telegram_delivery()

    assert first is not None
    assert first["post"]["vk_post_id"] == 102
    assert first["delivery"]["status"] == "processing"
    assert len(first["media"]) == 1
    assert first["media"][0]["media_type"] == "photo"

    second = await database.claim_next_telegram_delivery()

    assert second is not None
    assert second["post"]["vk_post_id"] == 101

    assert await database.claim_next_telegram_delivery() is None


@pytest.mark.asyncio
async def test_mark_delivery_published(database: Database) -> None:
    await add_post(database, 201, 100)

    item = await database.claim_next_telegram_delivery()
    assert item is not None

    delivery_id = item["delivery"]["id"]

    await database.mark_delivery_published(
        delivery_id,
        remote_message_id="12345",
    )

    delivery = await get_delivery(database, delivery_id)

    assert delivery["status"] == "published"
    assert delivery["remote_message_id"] == "12345"
    assert delivery["error"] is None
    assert delivery["outcome_uncertain"] == 0
    assert delivery["needs_review"] == 0


@pytest.mark.asyncio
async def test_mark_delivery_failed(database: Database) -> None:
    await add_post(database, 301, 100)

    item = await database.claim_next_telegram_delivery()
    assert item is not None

    delivery_id = item["delivery"]["id"]

    await database.mark_delivery_failed(
        delivery_id,
        error="Telegram rejected the request",
    )

    delivery = await get_delivery(database, delivery_id)

    assert delivery["status"] == "failed"
    assert delivery["error"] == "Telegram rejected the request"
    assert delivery["outcome_uncertain"] == 0
    assert delivery["needs_review"] == 0


@pytest.mark.asyncio
async def test_mark_delivery_uncertain(database: Database) -> None:
    await add_post(database, 401, 100)

    item = await database.claim_next_telegram_delivery()
    assert item is not None

    delivery_id = item["delivery"]["id"]

    await database.mark_delivery_uncertain(
        delivery_id,
        error="Telegram response timed out",
    )

    delivery = await get_delivery(database, delivery_id)

    assert delivery["status"] == "processing"
    assert delivery["outcome_uncertain"] == 1
    assert delivery["needs_review"] == 1

    # Неопределённое задание не должно выдаваться повторно.
    assert await database.claim_next_telegram_delivery() is None


@pytest.mark.asyncio
async def test_recover_interrupted_deliveries(database: Database) -> None:
    await add_post(database, 501, 100)

    item = await database.claim_next_telegram_delivery()
    assert item is not None

    telegram_delivery_id = item["delivery"]["id"]

    recovered = await database.recover_interrupted_deliveries()

    assert recovered == 1

    telegram_delivery = await get_delivery(
        database,
        telegram_delivery_id,
    )

    assert telegram_delivery["status"] == "processing"
    assert telegram_delivery["outcome_uncertain"] == 1
    assert telegram_delivery["needs_review"] == 1

    # MAX не должен измениться.
    cursor = await database._require_connection().execute(
        """
        SELECT status, outcome_uncertain, needs_review
        FROM deliveries
        WHERE post_id = ? AND platform = 'max'
        """,
        (item["post"]["id"],),
    )
    max_delivery = await cursor.fetchone()
    await cursor.close()

    assert max_delivery["status"] == "pending"
    assert max_delivery["outcome_uncertain"] == 0
    assert max_delivery["needs_review"] == 0

    # Повторное восстановление ничего не меняет.
    assert await database.recover_interrupted_deliveries() == 0

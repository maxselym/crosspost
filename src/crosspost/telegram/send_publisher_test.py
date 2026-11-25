import asyncio
from pathlib import Path

from aiogram import Bot

from crosspost.config import Settings
from crosspost.telegram.publisher import TelegramPublisher


async def main() -> None:
    settings = Settings()
    bot = Bot(token=settings.tg_bot_token.get_secret_value())
    publisher = TelegramPublisher(bot, settings.tg_chat_id)

    video_path = Path("media/file_example_MP4_1280_10MG.mp4")

    try:
        print("Testing photo publication...")

        photo_message = await publisher.publish_photo(
            "https://picsum.photos/1200/800",
            caption="<b>Тест TelegramPublisher</b>\nПроверка фотографии.",
        )

        print(f"Photo sent: message_id={photo_message.message_id}")
        print("\nTesting album publication...")

        album_messages = await publisher.publish_album(
            [
                "https://picsum.photos/1200/800?random=1",
                "https://picsum.photos/1200/800?random=2",
            ],
            caption="<b>Тест альбома Crosspost</b>\nДве фотографии.",
        )

        print(f"Album sent: {len(album_messages)} photos")

        for message in album_messages:
            print(f"Message ID: {message.message_id}")

        assert len(album_messages) == 2, "Expected 2 messages in album"

        print("\nTesting video publication...")

        video_message = await publisher.publish_video(
            video_path,
            caption="Тест загрузки видео через TelegramPublisher",
        )

        print(f"Video sent: message_id={video_message.message_id}")

        print("\nTelegramPublisher: OK")

    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

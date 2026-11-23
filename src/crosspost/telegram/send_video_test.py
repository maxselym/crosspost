import asyncio
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from crosspost.config import Settings


async def main() -> None:
    settings = Settings()

    video_path = Path("media/file_example_MP4_1280_10MG.mp4")

    if not video_path.is_file():
        raise FileNotFoundError(f"Video not found: {video_path.resolve()}")

    bot = Bot(token=settings.tg_bot_token.get_secret_value())

    try:
        print(f"Uploading: {video_path}")
        print(f"Size: {video_path.stat().st_size / 1024 / 1024:.2f} MiB")

        message = await bot.send_video(
            chat_id=settings.tg_chat_id,
            video=FSInputFile(video_path),
            caption="Тестовая загрузка MP4",
        )

        print("Video sent successfully")
        print(f"Message ID: {message.message_id}")

    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

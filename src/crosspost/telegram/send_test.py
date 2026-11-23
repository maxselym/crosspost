import asyncio

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from crosspost.config import Settings


async def main() -> None:
    settings = Settings()
    bot = Bot(token=settings.tg_bot_token.get_secret_value())

    try:
        message = await bot.send_photo(
            chat_id=settings.tg_chat_id,
            photo="https://picsum.photos/1200/800",
            caption=(
                "<b>Тестовая публикация Crosspost</b>\n\n"
                "Проверяем отправку текста, фотографии и ссылки на видео.\n\n"
                '🎬 <a href="https://vkvideo.ru/video-227892646_456239081">'
                "Смотреть видео</a>"
            ),
            parse_mode="HTML",
        )

        print("Telegram publication sent: OK")
        print(f"Chat ID: {message.chat.id}")
        print(f"Message ID: {message.message_id}")
        print(f"Photo attached: {bool(message.photo)}")

    except TelegramAPIError as exc:
        print(f"Telegram API error: {exc}")

    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

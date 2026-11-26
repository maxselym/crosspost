import asyncio

from aiogram import Bot

from crosspost.config import Settings

# Замените на токен вашего бота от @BotFather
CHANNEL_USERNAME = "@test_maxselym"


async def get_channel_id():
    settings = Settings()
    bot = Bot(token=settings.tg_bot_token.get_secret_value())
    try:
        # Получаем информацию о канале по его @username
        chat = await bot.get_chat(chat_id=CHANNEL_USERNAME)
        print(f"Название: {chat.title}")
        print(f"ID канала: {chat.id}")
    except Exception as e:
        print(f"Ошибка: {e}")
    finally:
        # Корректно закрываем сессию бота
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(get_channel_id())

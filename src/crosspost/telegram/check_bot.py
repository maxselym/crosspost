import asyncio

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from crosspost.config import Settings


async def main() -> None:
    settings = Settings()
    bot = Bot(token=settings.tg_bot_token.get_secret_value())

    try:
        me = await bot.get_me()

        print("Telegram bot connection: OK")
        print(f"ID: {me.id}")
        print(f"Username: @{me.username}")
        print(f"Name: {me.full_name}")
        print(f"Can join groups: {me.can_join_groups}")
        print(f"Can read all group messages: {me.can_read_all_group_messages}")
        print(f"Supports inline queries: {me.supports_inline_queries}")

    except TelegramAPIError as exc:
        print(f"Telegram API error: {exc}")

    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
from pathlib import Path

from crosspost.config import settings
from crosspost.storage.database import Database
from crosspost.vk.client import VKClient
from crosspost.vk.normalize import normalize_post


async def main() -> None:
    async with VKClient(
        token=settings.vk_access_token.get_secret_value(),
        api_version=settings.vk_api_version,
        timeout=settings.http_timeout_seconds,
    ) as vk:
        posts = await vk.get_wall_posts(
            owner_id=-settings.vk_group_id,
            count=10,
        )

    async with Database(Path("data/crosspost.db")) as db:
        await db.initialize()

        for raw_post in posts:
            post = normalize_post(raw_post, settings.vk_group_id)
            saved = await db.save_post(post)

            status = "СОХРАНЁН" if saved else "УЖЕ ЕСТЬ"

            print(f"{status}: VK post {post['vk_post_id']}, attachments={len(post['media'])}")


if __name__ == "__main__":
    asyncio.run(main())

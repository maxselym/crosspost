import asyncio

from crosspost.config import settings
from crosspost.vk.client import VKClient


async def main() -> None:
    async with VKClient(
        token=settings.vk_access_token.get_secret_value(),
        api_version=settings.vk_api_version,
        timeout=settings.http_timeout_seconds,
    ) as vk:
        posts = await vk.get_wall_posts(
            owner_id=-settings.vk_group_id,
            count=3,
        )

    print(f"Получено записей: {len(posts)}")

    for index, post in enumerate(posts, start=1):
        print(f"\nPOST #{index}")
        print(f"  id: {post.get('id')}")
        print(f"  owner_id: {post.get('owner_id')}")
        print(f"  date: {post.get('date')}")
        print(f"  text length: {len(post.get('text', ''))}")

        attachments = post.get("attachments", [])
        print(f"  attachments: {len(attachments)}")

        for attachment in attachments:
            kind = attachment.get("type", "unknown")
            data = attachment.get(kind, {})
            print(f"    - {kind}: keys={list(data.keys())}")


if __name__ == "__main__":
    asyncio.run(main())

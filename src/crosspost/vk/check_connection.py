import asyncio
from urllib.parse import urlsplit

import httpx

from crosspost.config import Settings
from crosspost.vk.client import VKClient


def print_attachments(attachments: list[dict], indent: str = "  ") -> None:
    for attachment in attachments:
        kind = attachment.get("type", "unknown")
        print(f"{indent}Attachment type: {kind}")

        if kind == "photo":
            photo = attachment.get("photo", {})
            print(f"{indent}  id={photo.get('id')}, owner_id={photo.get('owner_id')}")

            for size in photo.get("sizes", []):
                print(
                    f"{indent}  size: "
                    f"type={size.get('type')}, "
                    f"width={size.get('width')}, "
                    f"height={size.get('height')}"
                )

        elif kind == "video":
            video = attachment.get("video", {})
            player = video.get("player")

            print(f"{indent}  id={video.get('id')}, owner_id={video.get('owner_id')}")
            print(f"{indent}  title={video.get('title')!r}, duration={video.get('duration')}")
            print(f"{indent}  access_key_present={bool(video.get('access_key'))}")

            if player:
                print(f"{indent}  player_host={urlsplit(player).hostname}")

            print(f"{indent}  video_fields={sorted(video.keys())}")

        else:
            obj = attachment.get(kind, {})
            print(f"{indent}  fields={sorted(obj.keys())}")

    if not attachments:
        print(f"{indent}No attachments")


def inspect_post(post: dict, level: int = 0) -> None:
    indent = "  " * level

    print(f"\n{indent}Post ID: {post.get('id')}")
    print(f"{indent}Owner ID: {post.get('owner_id')}")
    print_attachments(post.get("attachments", []), indent + "  ")

    for original in post.get("copy_history", []):
        print(f"\n{indent}Reposted original:")
        inspect_post(original, level + 1)


async def main() -> None:
    settings = Settings()

    print("Connecting to VK API...")

    try:
        async with VKClient(
            token=settings.vk_access_token.get_secret_value(),
            api_version=settings.vk_api_version,
        ) as vk:
            posts = await vk.get_wall_posts(
                owner_id=-settings.vk_group_id,
                count=10,
            )

        print(f"Posts received: {len(posts)}")

        for post in posts:
            inspect_post(post)

    except httpx.HTTPStatusError as exc:
        print(f"HTTP error: status {exc.response.status_code}")

    except httpx.RequestError as exc:
        print(f"Network error: {type(exc).__name__}")

    except RuntimeError as exc:
        print(str(exc))

    except Exception as exc:
        print(f"Unexpected error: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())

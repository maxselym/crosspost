import asyncio
from pathlib import Path

import httpx

from crosspost.config import Settings
from crosspost.media.downloader import MediaDownloader
from crosspost.vk.client import VKClient


PHOTO_ID = 456245152
OUTPUT_DIR = Path("data/media/vk")


async def main() -> None:
    settings = Settings()  # pyright: ignore[reportCallIssue]

    async with VKClient(
        token=settings.vk_access_token.get_secret_value(),
        api_version=settings.vk_api_version,
    ) as vk:
        posts = await vk.get_wall_posts(
            owner_id=-settings.vk_group_id,
            count=20,
        )

    photo = None

    for post in posts:
        for attachment in post.get("attachments", []):
            if attachment.get("type") != "photo":
                continue

            candidate = attachment.get("photo", {})

            if candidate.get("id") == PHOTO_ID:
                photo = candidate
                break

        if photo:
            break

    if not photo:
        raise RuntimeError(f"Photo {PHOTO_ID} not found")

    sizes = photo.get("sizes", [])

    if not sizes:
        raise RuntimeError("Photo has no available sizes")

    largest = max(
        sizes,
        key=lambda item: item.get("width", 0) * item.get("height", 0),
    )

    url = largest.get("url")

    if not url:
        raise RuntimeError("Photo URL is missing")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    destination = OUTPUT_DIR / f"photo_{PHOTO_ID}.jpg"

    async with httpx.AsyncClient(
        timeout=60,
        follow_redirects=True,
    ) as client:
        downloader = MediaDownloader(client)
        result = await downloader.download(url, destination)

    with result.open("rb") as file:
        signature = file.read(3)

    if signature != b"\xff\xd8\xff":
        result.unlink(missing_ok=True)
        raise RuntimeError("Downloaded file is not a JPEG image")

    print(f"Downloaded: {result}")
    print(f"Size: {result.stat().st_size:,} bytes")
    print(f"Resolution: {largest.get('width')}x{largest.get('height')}")


if __name__ == "__main__":
    asyncio.run(main())

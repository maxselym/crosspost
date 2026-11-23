import asyncio
from urllib.parse import urlsplit

import httpx

from crosspost.config import Settings
from crosspost.vk.client import VKClient


PHOTO_ID = 456245152
VIDEO_ID = 456239081
VIDEO_OWNER_ID = -227892646

MEDIA_TIMEOUT = 20.0
VK_TIMEOUT = 15.0


def get_host(url: str) -> str:
    return urlsplit(url).hostname or "unknown"


async def check_media_url(url: str, label: str) -> None:
    print(f"{label} URL host: {get_host(url)}")

    try:
        async with httpx.AsyncClient(
            timeout=MEDIA_TIMEOUT,
            follow_redirects=True,
        ) as client:
            response = await client.get(
                url,
                headers={"Range": "bytes=0-0"},
            )

        print(f"HTTP status: {response.status_code}")
        print(f"Final host: {get_host(str(response.url))}")
        print(f"Content-Type: {response.headers.get('content-type')}")
        print(f"Content-Length: {response.headers.get('content-length')}")
        print(f"Content-Range: {response.headers.get('content-range')}")
        if label == "Video":
            print(f"Response URL path: {urlsplit(str(response.url)).path}")
            print(f"HTML title present: {'<title' in response.text.lower()}")
            print(f"Contains video tag: {'<video' in response.text.lower()}")
            print(f"Contains m3u8: {'.m3u8' in response.text.lower()}")
            print(f"Contains mp4: {'.mp4' in response.text.lower()}")
            html = response.text.lower()
            markers = [
                "player",
                "video",
                "stream",
                "hls",
                "dash",
                "manifest",
                "m3u8",
                "mp4",
                "vkvideo",
                "__initialstate",
            ]

            print("HTML markers:")

            for marker in markers:
                print(f"  {marker}: {marker in html}")

    except httpx.RequestError as exc:
        print(f"{label} network error: {type(exc).__name__}")


async def check_photo(photo: dict) -> None:
    sizes = photo.get("sizes", [])

    if not sizes:
        print("PHOTO: no sizes found")
        return

    size = max(
        sizes,
        key=lambda item: item.get("width", 0) * item.get("height", 0),
    )

    url = size.get("url")

    if not url:
        print("PHOTO: selected size has no URL")
        return

    print("\nPHOTO")
    print(f"Selected size: type={size.get('type')}, {size.get('width')}x{size.get('height')}")

    await check_media_url(url, "Photo CDN")


async def check_video(
    token: str,
    api_version: str,
    video: dict,
) -> None:
    owner_id = video.get("owner_id", VIDEO_OWNER_ID)
    video_id = video.get("id", VIDEO_ID)
    access_key = video.get("access_key")

    video_ref = f"{owner_id}_{video_id}"

    if access_key:
        video_ref += f"_{access_key}"

    print("\nVIDEO")
    print(f"Video ID: {video_id}")
    print(f"Owner ID: {owner_id}")
    print(f"Access key present: {bool(access_key)}")

    try:
        async with httpx.AsyncClient(
            base_url="https://api.vk.com/method/",
            timeout=VK_TIMEOUT,
        ) as client:
            response = await client.get(
                "video.get",
                params={
                    "videos": video_ref,
                    "access_token": token,
                    "v": api_version,
                },
            )

        response.raise_for_status()
        data = response.json()

    except httpx.HTTPStatusError as exc:
        print(f"VIDEO HTTP error: status {exc.response.status_code}")
        return

    except httpx.RequestError as exc:
        print(f"VIDEO network error: {type(exc).__name__}")
        return

    except ValueError:
        print("VIDEO: invalid JSON response")
        return

    if "error" in data:
        error = data["error"]
        print(f"VK API error: {error.get('error_code')} — {error.get('error_msg')}")
        return

    items = data.get("response", {}).get("items", [])
    print(f"Videos returned: {len(items)}")

    for item in items:
        print(f"Title: {item.get('title')!r}")
        print(f"Duration: {item.get('duration')}")
        print(f"Available fields: {sorted(item.keys())}")

        files = item.get("files") or {}
        print(f"Files available: {bool(files)}")
        print(f"File variants: {sorted(files.keys())}")

        direct_url = item.get("direct_url")

        if isinstance(direct_url, str) and direct_url:
            await check_media_url(direct_url, "Video")
        else:
            print("Direct URL: absent")

        for name, file_url in files.items():
            if isinstance(file_url, str) and file_url:
                print(f"  {name}: host={get_host(file_url)}")


async def main() -> None:
    settings = Settings()  # pyright: ignore[reportCallIssue]

    print("Loading VK wall attachments...")

    try:
        async with VKClient(
            token=settings.vk_access_token.get_secret_value(),
            api_version=settings.vk_api_version,
        ) as vk:
            posts = await vk.get_wall_posts(
                owner_id=-settings.vk_group_id,
                count=20,
            )

    except httpx.HTTPStatusError as exc:
        print(f"VK wall HTTP error: status {exc.response.status_code}")
        return

    except httpx.RequestError as exc:
        print(f"VK wall network error: {type(exc).__name__}")
        return

    except RuntimeError as exc:
        print(f"VK API error: {exc}")
        return

    photo = None
    video = None

    for post in posts:
        for attachment in post.get("attachments", []):
            kind = attachment.get("type")

            if kind == "photo":
                candidate = attachment.get("photo", {})

                if candidate.get("id") == PHOTO_ID:
                    photo = candidate

            elif kind == "video":
                candidate = attachment.get("video", {})

                if candidate.get("id") == VIDEO_ID:
                    video = candidate

    if photo:
        await check_photo(photo)
    else:
        print(f"\nPHOTO {PHOTO_ID}: not found in latest 20 posts")

    if video:
        await check_video(
            settings.vk_access_token.get_secret_value(),
            settings.vk_api_version,
            video,
        )
    else:
        print(f"\nVIDEO {VIDEO_ID}: not found in latest 20 posts")


if __name__ == "__main__":
    asyncio.run(main())

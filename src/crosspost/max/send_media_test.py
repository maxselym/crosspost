from __future__ import annotations

import argparse
import json
import mimetypes
import ssl
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from crosspost.config import settings

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".tiff", ".bmp", ".heic"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}

IMAGE_MAX_SIZE = 50 * 1024 * 1024
VIDEO_MAX_SIZE = 250 * 1024 * 1024


def create_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()

    if settings.max_ca_file is not None:
        context.load_verify_locations(cafile=settings.max_ca_file)

    return context


def get_media_type(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix in IMAGE_EXTENSIONS:
        return "image"

    if suffix in VIDEO_EXTENSIONS:
        return "video"

    raise ValueError(f"Unsupported file extension: {suffix}")


def get_upload_token(data: dict[str, Any], media_type: str) -> str:
    if media_type == "video":
        token = data.get("token")
    else:
        photos = data.get("photos", {})

        if not isinstance(photos, dict) or not photos:
            raise RuntimeError("MAX response does not contain photos")

        # MAX возвращает фотографии в виде словаря с числовыми ключами.
        first_photo = next(iter(photos.values()))

        if not isinstance(first_photo, dict):
            raise RuntimeError("Unexpected photo data format")

        token = first_photo.get("token")

    if not token:
        raise RuntimeError("MAX response does not contain media token")

    return str(token)


def upload_media(
    client: httpx.Client,
    path: Path,
    media_type: str,
    api_url: str,
    token: str,
) -> str:
    # Step 1. Request an upload URL.
    response = client.post(
        f"{api_url}/uploads",
        params={"type": media_type},
        headers={"Authorization": token},
        timeout=30,
    )
    response.raise_for_status()

    upload_data = response.json()
    upload_url = upload_data.get("url")

    if not upload_url:
        raise RuntimeError("MAX API did not return an upload URL")

    # For video, the token is returned by POST /uploads.
    media_token = upload_data.get("token") if media_type == "video" else None

    # Step 2. Upload the actual file.
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    try:
        with path.open("rb") as file:
            upload_response = client.post(
                upload_url,
                files={"data": (path.name, file, mime_type)},
                timeout=300,
            )
            upload_response.raise_for_status()

            if media_type == "image":
                upload_data = upload_response.json()
                media_token = get_upload_token(upload_data, media_type)

            elif upload_response.text.strip() != "<retval>1</retval>":
                # Some responses may contain XML with formatting.
                if "<retval>1</retval>" not in upload_response.text:
                    raise RuntimeError("Video upload was not confirmed")

    except httpx.HTTPError:
        raise RuntimeError("Media upload request failed") from None

    if not media_token:
        raise RuntimeError("MAX did not return a media token")

    return str(media_token)


def publish_media(
    client: httpx.Client,
    api_url: str,
    chat_id: int,
    token: str,
    media_type: str,
    caption: str,
) -> dict[str, Any]:
    payload = {
        "text": caption,
        "attachments": [
            {
                "type": media_type,
                "payload": {"token": token},
            }
        ],
    }

    # MAX may need time to process the uploaded media.
    for attempt in range(4):
        response = client.post(
            f"{api_url}/messages",
            params={"chat_id": chat_id},
            headers={"Authorization": settings.max_bot_token.get_secret_value()},
            json=payload,
            timeout=60,
        )

        if response.status_code >= 400:
            try:
                error_data = response.json()
            except ValueError:
                error_data = {}

            if error_data.get("code") == "attachment.not.ready" and attempt < 3:
                delay = 2 ** (attempt + 1)
                print(f"Media is still processing. Waiting {delay} sec...")
                time.sleep(delay)
                continue

            response.raise_for_status()

        return response.json()

    raise RuntimeError("Media processing did not finish in time")


def main() -> int:
    parser = argparse.ArgumentParser(description="Test MAX photo/video publication")
    parser.add_argument("file", type=Path, help="Path to image or video")
    parser.add_argument(
        "--caption",
        default="Тест публикации через MAX Bot API",
        help="Message text",
    )
    args = parser.parse_args()

    path = args.file.resolve()

    if not path.is_file():
        print(f"File not found: {path}")
        return 1

    try:
        media_type = get_media_type(path)
    except ValueError as exc:
        print(exc)
        return 1

    size = path.stat().st_size
    max_size = IMAGE_MAX_SIZE if media_type == "image" else VIDEO_MAX_SIZE

    print("MAX media publication test")
    print("=" * 40)
    print("File:", path.name)
    print("Type:", media_type)
    print(f"Size: {size / 1024 / 1024:.2f} MB")

    if size > max_size:
        print(f"ERROR: Maximum allowed size is {max_size / 1024 / 1024:.0f} MB")
        return 1

    api_url = str(settings.max_api_url).rstrip("/")
    ssl_context = create_ssl_context()

    try:
        with httpx.Client(
            verify=ssl_context,
            follow_redirects=True,
        ) as client:
            print("\n[1] Requesting upload and uploading media...")

            media_token = upload_media(
                client,
                path,
                media_type,
                api_url,
                settings.max_bot_token.get_secret_value(),
            )
            print("Upload: OK")

            print("\n[2] Publishing message...")

            result = publish_media(
                client,
                api_url,
                settings.max_chat_id,
                media_token,
                media_type,
                args.caption,
            )

            print("Publication: OK")
            print("\nResponse:")
            print(json.dumps(result, ensure_ascii=False, indent=2)[:3000])

    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        print(f"\nERROR: {exc}")
        return 1

    print("\nMAX media publication test: SUCCESS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

from typing import Any


def _get_photo_url(photo: dict[str, Any]) -> str | None:
    """Возвращает URL самого большого доступного размера фотографии."""
    sizes = photo.get("sizes", [])

    if not sizes:
        return None

    largest = max(
        sizes,
        key=lambda item: item.get("width", 0) * item.get("height", 0),
    )

    return largest.get("url")


def normalize_post(post: dict[str, Any], vk_group_id: int) -> dict[str, Any]:
    """Преобразует запись wall.get в структуру для хранения в SQLite."""
    post_id = post.get("id")
    owner_id = post.get("owner_id")
    post_date = post.get("date")

    if post_id is None or owner_id is None or post_date is None:
        raise ValueError("VK post is missing id, owner_id or date")

    media = []

    for attachment in post.get("attachments", []):
        media_type = attachment.get("type", "unknown")
        data = attachment.get(media_type, {})

        if not isinstance(data, dict):
            data = {}

        original_url = None

        if media_type == "photo":
            original_url = _get_photo_url(data)
        elif media_type == "link":
            original_url = data.get("url")
        elif media_type == "video":
            video_owner_id = data.get("owner_id")
            video_id = data.get("id")

            if video_owner_id is not None and video_id is not None:
                original_url = f"https://vk.com/video{video_owner_id}_{video_id}"

        media.append(
            {
                "media_type": media_type,
                "original_url": original_url,
                "raw_json": attachment,
            }
        )

    return {
        "vk_group_id": vk_group_id,
        "vk_post_id": post_id,
        "owner_id": owner_id,
        "post_date": post_date,
        "text": post.get("text", ""),
        "source_url": f"https://vk.com/wall{owner_id}_{post_id}",
        "raw_json": post,
        "media": media,
    }

from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile, InputMediaPhoto, MediaUnion, Message


class TelegramPublisher:
    def __init__(self, bot: Bot, chat_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id

    async def publish_text(
        self,
        text: str,
        *,
        parse_mode: str | None = "HTML",
    ) -> Message:
        return await self._bot.send_message(
            chat_id=self._chat_id,
            text=text,
            parse_mode=parse_mode,
        )

    async def publish_photo(
        self,
        photo: str | Path,
        *,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
    ) -> Message:
        photo_input = FSInputFile(photo) if isinstance(photo, Path) else photo

        return await self._bot.send_photo(
            chat_id=self._chat_id,
            photo=photo_input,
            caption=caption,
            parse_mode=parse_mode,
        )

    async def publish_video(
        self,
        video: Path,
        *,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
    ) -> Message:
        if not video.is_file():
            raise FileNotFoundError(f"Video not found: {video.resolve()}")

        return await self._bot.send_video(
            chat_id=self._chat_id,
            video=FSInputFile(video),
            caption=caption,
            parse_mode=parse_mode,
        )

    async def publish_album(
        self,
        photos: list[str | Path],
        *,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
    ) -> list[Message]:
        if not 2 <= len(photos) <= 10:
            raise ValueError("Telegram album must contain 2 to 10 photos")

        media: list[MediaUnion] = []

        for index, photo in enumerate(photos):
            if isinstance(photo, Path):
                if not photo.is_file():
                    raise FileNotFoundError(f"Photo not found: {photo.resolve()}")
                photo_input = FSInputFile(photo)
            else:
                photo_input = photo

            media.append(
                InputMediaPhoto(
                    media=photo_input,
                    caption=caption if index == 0 else None,
                    parse_mode=parse_mode if index == 0 else None,
                )
            )

        return await self._bot.send_media_group(
            chat_id=self._chat_id,
            media=media,
        )

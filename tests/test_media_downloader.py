from pathlib import Path

import httpx
import pytest
import respx

from crosspost.media.downloader import MediaDownloader


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("media_type", "content_type", "payload"),
    [
        (
            "photo",
            "image/jpeg",
            b"\xff\xd8\xff\xe0test-jpeg-data",
        ),
        (
            "video",
            "video/mp4",
            b"\x00\x00\x00\x18ftypmp42test-video-data",
        ),
    ],
)
async def test_download_media(
    tmp_path: Path,
    media_type: str,
    content_type: str,
    payload: bytes,
) -> None:
    url = f"https://cdn.example.com/{media_type}"
    destination = tmp_path / f"test.{media_type}"

    with respx.mock:
        route = respx.get(url).mock(
            return_value=httpx.Response(
                200,
                content=payload,
                headers={"Content-Type": content_type},
            )
        )

        async with httpx.AsyncClient() as client:
            downloader = MediaDownloader(client)

            result = await downloader.download(
                url,
                destination,
            )

    assert route.called
    assert result == destination
    assert destination.exists()
    assert destination.read_bytes() == payload
    assert not list(tmp_path.glob(".*.part"))


@pytest.mark.asyncio
async def test_download_http_error(
    tmp_path: Path,
) -> None:
    url = "https://cdn.example.com/missing"
    destination = tmp_path / "missing.jpg"

    with respx.mock:
        route = respx.get(url).mock(return_value=httpx.Response(404))

        async with httpx.AsyncClient() as client:
            downloader = MediaDownloader(client)

            with pytest.raises(httpx.HTTPStatusError):
                await downloader.download(url, destination)

    assert route.called
    assert not destination.exists()
    assert not list(tmp_path.glob(".*.part"))


@pytest.mark.asyncio
async def test_download_replaces_existing_file(
    tmp_path: Path,
) -> None:
    url = "https://cdn.example.com/photo"
    destination = tmp_path / "photo.jpg"

    destination.write_bytes(b"old-content")
    new_content = b"new-photo-content"

    with respx.mock:
        respx.get(url).mock(
            return_value=httpx.Response(
                200,
                content=new_content,
            )
        )

        async with httpx.AsyncClient() as client:
            downloader = MediaDownloader(client)

            await downloader.download(url, destination)

    assert destination.read_bytes() == new_content
    assert not list(tmp_path.glob(".*.part"))


class FailingStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"partial-content"
        raise httpx.ReadError("Connection lost")

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_download_network_error_preserves_existing_file(
    tmp_path: Path,
) -> None:
    url = "https://cdn.example.com/broken"
    destination = tmp_path / "photo.jpg"

    destination.write_bytes(b"old-content")

    with respx.mock:
        route = respx.get(url).mock(
            return_value=httpx.Response(
                200,
                stream=FailingStream(),
            )
        )

        async with httpx.AsyncClient() as client:
            downloader = MediaDownloader(client)

            with pytest.raises(httpx.ReadError):
                await downloader.download(url, destination)

    assert route.called
    assert destination.read_bytes() == b"old-content"
    assert not list(tmp_path.glob(".*.part"))

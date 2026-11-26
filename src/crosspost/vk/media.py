import os
import tempfile
from pathlib import Path

import httpx


class MediaDownloader:
    def __init__(
        self,
        client: httpx.AsyncClient,
        chunk_size: int = 64 * 1024,
    ) -> None:
        self._client = client
        self._chunk_size = chunk_size

    async def download(
        self,
        url: str,
        destination: Path,
    ) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".part",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)

        try:
            async with self._client.stream("GET", url) as response:
                response.raise_for_status()

                with temporary_path.open("wb") as output:
                    async for chunk in response.aiter_bytes(chunk_size=self._chunk_size):
                        output.write(chunk)

            os.replace(temporary_path, destination)

        finally:
            temporary_path.unlink(missing_ok=True)

        return destination

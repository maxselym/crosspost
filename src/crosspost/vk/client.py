import httpx


class VKClient:
    BASE_URL = "https://api.vk.com/method/"

    def __init__(
        self,
        token: str,
        api_version: str,
        timeout: float = 15.0,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=timeout,
        )
        self._token = token
        self._api_version = api_version

    async def get_wall_posts(
        self,
        owner_id: int,
        count: int = 10,
    ) -> list[dict]:
        response = await self._client.get(
            "wall.get",
            params={
                "owner_id": owner_id,
                "count": count,
                "access_token": self._token,
                "v": self._api_version,
            },
        )

        response.raise_for_status()
        data = response.json()

        if "error" in data:
            error = data["error"]
            code = error.get("error_code", "unknown")
            message = error.get("error_msg", "Unknown VK API error")
            raise RuntimeError(f"VK API error {code}: {message}")

        return data["response"]["items"]

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "VKClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

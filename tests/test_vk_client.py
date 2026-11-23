import httpx
import pytest
import respx

from crosspost.vk.client import VKClient


@pytest.mark.asyncio
async def test_get_wall_posts():
    token = "test-token"
    api_version = "5.199"

    with respx.mock(base_url="https://api.vk.com") as router:
        route = router.get("/method/wall.get").mock(
            return_value=httpx.Response(
                200,
                json={
                    "response": {
                        "count": 1,
                        "items": [
                            {
                                "id": 123,
                                "text": "Тестовая запись",
                                "date": 1700000000,
                            }
                        ],
                    }
                },
            )
        )

        async with VKClient(token=token, api_version=api_version) as vk:
            posts = await vk.get_wall_posts(owner_id=-123456, count=10)

        assert route.called

        request = route.calls.last.request
        assert request.url.params["owner_id"] == "-123456"
        assert request.url.params["count"] == "10"
        assert request.url.params["access_token"] == token
        assert request.url.params["v"] == api_version

        assert len(posts) == 1
        assert posts[0]["id"] == 123
        assert posts[0]["text"] == "Тестовая запись"

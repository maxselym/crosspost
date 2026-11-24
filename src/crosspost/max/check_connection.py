import json

import httpx

from crosspost.config import settings


def print_response(response: httpx.Response) -> dict | None:
    print(f"HTTP: {response.status_code}")

    try:
        data = response.json()
    except ValueError:
        print(response.text[:1000])
        return None

    if not response.is_success:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return None

    if data.get("success") is False:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return None

    return data


def main() -> None:
    base_url = str(settings.max_api_url).rstrip("/")
    token = settings.max_bot_token.get_secret_value()

    verify = str(settings.max_ca_file) if settings.max_ca_file is not None else True

    headers = {"Authorization": token}

    print("MAX connection test")
    print("=" * 40)

    try:
        with httpx.Client(
            verify=verify,
            timeout=20,
            headers=headers,
        ) as client:
            # 1. Проверка авторизации бота
            print("\n[1] Bot authorization: GET /me")

            response = client.get(f"{base_url}/me")
            bot = print_response(response)

            if bot is None:
                print("Bot authorization: FAILED")
                return

            print("Bot authorization: OK")
            print("User ID:", bot.get("user_id"))
            print("Name:", bot.get("first_name"))
            print("Username:", bot.get("username"))
            print("Is bot:", bot.get("is_bot"))

            # 2. Проверка доступа к чату
            chat_id = settings.max_chat_id

            print(f"\n[2] Chat information: GET /chats/{chat_id}")

            response = client.get(f"{base_url}/chats/{chat_id}")
            chat = print_response(response)

            if chat is None:
                print("Chat access: FAILED")
                return

            print("Chat access: OK")
            print("Chat ID:", chat.get("chat_id"))
            print("Title:", chat.get("title"))
            print("Type:", chat.get("type"))

            # 3. Проверка членства бота
            print(f"\n[3] Bot membership: GET /chats/{chat_id}/members/me")

            response = client.get(f"{base_url}/chats/{chat_id}/members/me")
            membership = print_response(response)

            if membership is None:
                print("Membership check: FAILED")
                return

            print("Membership check: OK")
            print(
                json.dumps(
                    membership,
                    ensure_ascii=False,
                    indent=2,
                )
            )

            print("\n" + "=" * 40)
            print("MAX connection test: SUCCESS")

    except httpx.HTTPError as exc:
        print("\nConnection error:", type(exc).__name__, exc)


if __name__ == "__main__":
    main()

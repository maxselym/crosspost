import sqlite3
from pathlib import Path


DB_PATH = Path("data/crosspost.db")


def main() -> None:
    with sqlite3.connect(DB_PATH) as connection:
        print("DATABASE:", DB_PATH.resolve())

        for table in ("posts", "media", "deliveries"):
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"{table}: {count}")

        print("\nPOSTS:")

        posts = connection.execute(
            """
            SELECT
                p.id,
                p.vk_post_id,
                LENGTH(p.text),
                p.source_url
            FROM posts p
            ORDER BY p.vk_post_id
            """
        ).fetchall()

        for post_id, vk_post_id, text_length, source_url in posts:
            print(f"\nVK {vk_post_id}: text={text_length}, url={source_url}")

            media = connection.execute(
                """
                SELECT media_type, COUNT(*)
                FROM media
                WHERE post_id = ?
                GROUP BY media_type
                """,
                (post_id,),
            ).fetchall()

            for media_type, count in media:
                print(f"  media: {media_type} = {count}")

            deliveries = connection.execute(
                """
                SELECT platform, status
                FROM deliveries
                WHERE post_id = ?
                ORDER BY platform
                """,
                (post_id,),
            ).fetchall()

            for platform, status in deliveries:
                print(f"  delivery: {platform} = {status}")


if __name__ == "__main__":
    main()

import asyncio
import json
from pathlib import Path

from crosspost.storage.database import Database

PROJECT_ROOT = Path(__file__).resolve().parents[2]


async def main():
    db = Database(PROJECT_ROOT / "data" / "crosspost.db")
    await db.connect()

    try:
        conn = db._require_connection()
        cursor = await conn.execute(
            """
            SELECT raw_json
            FROM media
            WHERE media_type = 'video'
            LIMIT 1
            """
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row:
            print(json.dumps(json.loads(row["raw_json"]), ensure_ascii=False, indent=2))
        else:
            print("Видео в базе не найдено")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
from pathlib import Path

from crosspost.storage.database import Database


async def main() -> None:
    db_path = Path("data/crosspost.db")

    async with Database(db_path) as db:
        await db.initialize()

    print(f"Database initialized: {db_path.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())

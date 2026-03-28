"""Initialize database schema for the Telegram bot."""

import asyncio

from database import DatabaseRepository


async def main() -> None:
    db = DatabaseRepository()
    try:
        await db.init_db()
        print("Database initialized successfully.")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())

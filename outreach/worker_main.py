from __future__ import annotations

import asyncio
import logging

from outreach.database import close_database, initialize_database
from outreach.worker import worker_loop


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await initialize_database()
    try:
        await worker_loop()
    finally:
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())

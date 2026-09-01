"""Manually provision only the Admin notification persistence tables."""

import asyncio
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.settings_admin import admin_settings  # noqa: E402
from app.db.admin_notification_provisioning import (  # noqa: E402
    create_admin_notification_tables,
)
from app.db.engine import configure_database_url, dispose_engine, get_engine  # noqa: E402


async def provision() -> tuple[str, ...]:
    configure_database_url(admin_settings.database_url)
    engine = get_engine()
    try:
        async with engine.begin() as connection:
            return await connection.run_sync(create_admin_notification_tables)
    finally:
        await dispose_engine()


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    created = asyncio.run(provision())
    for table_name in created:
        print(table_name)


if __name__ == "__main__":
    main()

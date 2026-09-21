"""Manual Staff-only schema preparation. No registration or seeding."""

import asyncio
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


async def provision() -> tuple[str, ...]:
    from app.core.settings_admin import admin_settings
    from app.db.admin_staff_provisioning import create_admin_staff_tables
    from app.db.engine import configure_database_url, dispose_engine, get_engine

    configure_database_url(admin_settings.database_url)
    try:
        async with get_engine().begin() as connection:
            return await connection.run_sync(create_admin_staff_tables)
    finally:
        await dispose_engine()


def main() -> int:
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        names = asyncio.run(provision())
    except Exception:
        print("Staff table preparation failed.", file=sys.stderr)
        return 1
    print("Prepared: " + ", ".join(names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

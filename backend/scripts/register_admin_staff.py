"""Read one approved StaffRegistration JSON object from stdin; never an ID Token."""

import asyncio
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


async def register(registration) -> None:
    from app.core.settings_admin import admin_settings
    from app.db.admin_staff_provisioning import register_admin_staff
    from app.db.engine import configure_database_url, dispose_engine, get_engine

    configure_database_url(admin_settings.database_url)
    try:
        async with get_engine().begin() as connection:
            await connection.run_sync(register_admin_staff, registration)
    finally:
        await dispose_engine()


def main() -> int:
    try:
        from app.db.admin_staff_provisioning import StaffRegistration
        registration = StaffRegistration.model_validate_json(sys.stdin.read())
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(register(registration))
    except Exception:
        # Validation and driver errors may contain PII or connection details.
        print("Staff registration failed.", file=sys.stderr)
        return 1
    print("Staff registration completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Deterministically export owner-specific public OpenAPI artifacts."""

import argparse
import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

OUTPUTS = {
    "line": BACKEND_ROOT / "contracts" / "line-api-v1.openapi.json",
    "admin": BACKEND_ROOT / "contracts" / "admin-api-v1.openapi.json",
}


def schema(owner: str) -> dict:
    if owner == "line":
        from app.core.settings_line import LineSettings
        from app.main_line import create_line_app

        document = create_line_app(LineSettings(app_env="production")).openapi()
    else:
        from app.core.settings_admin import AdminSettings
        from app.main_admin import create_admin_app

        document = create_admin_app(AdminSettings(app_env="production")).openapi()
    document["x-contract-owner"] = owner
    document["x-contract-version"] = "1.0.0"
    return document


def serialize(owner: str) -> str:
    return json.dumps(schema(owner), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("owner", choices=("line", "admin", "all"), default="all", nargs="?")
    owner_arg = parser.parse_args().owner
    selected = OUTPUTS if owner_arg == "all" else (owner_arg,)
    for owner in selected:
        OUTPUTS[owner].write_text(serialize(owner), encoding="utf-8")


if __name__ == "__main__":
    main()

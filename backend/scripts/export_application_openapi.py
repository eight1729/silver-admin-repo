"""Deterministically export the Admin Public v1 OpenAPI artifact."""

import argparse
import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

OUTPUT = BACKEND_ROOT / "contracts" / "admin-api-v1.openapi.json"


def schema() -> dict:
    from app.core.settings_admin import AdminSettings
    from app.main_admin import create_admin_app

    document = create_admin_app(AdminSettings(app_env="production")).openapi()
    document["x-contract-owner"] = "admin"
    document["x-contract-version"] = "1.0.0"
    return document


def serialize() -> str:
    return json.dumps(schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    OUTPUT.write_text(serialize(), encoding="utf-8")


if __name__ == "__main__":
    main()

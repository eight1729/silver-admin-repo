"""Export the Admin internal contract without loading settings or .env files."""

import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import FastAPI
from app.api.routes.admin_internal import router
from app.schemas.admin_internal import ADMIN_INTERNAL_CONTRACT_VERSION

OUTPUT = BACKEND_ROOT / "contracts" / "admin-internal-api-v1.openapi.json"


def schema() -> dict:
    app = FastAPI(title="Silver Admin Internal API", version=ADMIN_INTERNAL_CONTRACT_VERSION)
    app.include_router(router)
    document = app.openapi()
    document["x-contract-owner"] = "admin"
    document["x-contract-version"] = ADMIN_INTERNAL_CONTRACT_VERSION
    return document


def serialize() -> str:
    return json.dumps(schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    OUTPUT.write_text(serialize(), encoding="utf-8")

"""Partner API-key authentication without LINE runtime dependencies."""

import hmac
from typing import AsyncGenerator

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.security import sha256_hex
from app.db import repositories
from app.db.engine import db_connection


async def get_partner_conn() -> AsyncGenerator[AsyncConnection, None]:
    async with db_connection() as conn:
        yield conn


_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def authenticate_partner(
    api_key: str | None = Depends(_api_key_header),
    conn: AsyncConnection = Depends(get_partner_conn),
) -> str:
    if not api_key:
        raise HTTPException(status_code=401, detail={"error": "api_key_required"})
    key_id, sep, secret = api_key.partition(".")
    if not sep or not key_id or not secret:
        raise HTTPException(status_code=403, detail={"error": "invalid_api_key"})
    app = await repositories.get_app_by_api_key_id(conn, key_id)
    if app is None or not hmac.compare_digest(sha256_hex(secret), app["api_key_hash"]):
        raise HTTPException(status_code=403, detail={"error": "invalid_api_key"})
    return app["app_id"]


async def get_authorized_partner_service(
    service_id: str,
    app_id: str = Depends(authenticate_partner),
    conn: AsyncConnection = Depends(get_partner_conn),
) -> dict:
    service = await repositories.get_service_for_app(conn, service_id, app_id)
    if service is None:
        raise HTTPException(status_code=404, detail={"error": "service_not_found"})
    return service

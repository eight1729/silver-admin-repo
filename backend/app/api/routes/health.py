from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db.engine import db_connection

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/health/db")
async def health_db() -> JSONResponse:
    try:
        async with db_connection() as conn:
            await conn.execute(text("SELECT 1"))
        return JSONResponse(content={"status": "ok", "database": "connected"})
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "unavailable"},
        )

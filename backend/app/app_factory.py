"""Small infrastructure shared by the two deployable FastAPI entrypoints."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.db.engine import dispose_engine
from app.services.http_client import aclose_client


@asynccontextmanager
async def shared_lifespan(app: FastAPI):
    yield
    await dispose_engine()
    await aclose_client()


def configure_shared_infrastructure(
    app: FastAPI,
    cors_origins: str,
    *,
    additional_allowed_headers: tuple[str, ...] = (),
) -> None:
    origins = tuple(value.strip() for value in cors_origins.split(",") if value.strip())
    if origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=origins,
            allow_methods=["GET", "POST", "PUT", "OPTIONS"],
            allow_headers=[
                "Authorization", "Content-Type", "X-API-Key", "Idempotency-Key",
                *additional_allowed_headers,
            ],
            allow_credentials=False,
        )

    @app.exception_handler(OperationalError)
    async def db_unavailable(request: Request, exc: OperationalError):
        return JSONResponse(
            content={"detail": {"error": "database_unavailable"}},
            status_code=503,
        )

    @app.exception_handler(SQLAlchemyError)
    async def db_error(request: Request, exc: SQLAlchemyError):
        return JSONResponse(
            content={"detail": {"error": "internal_error"}},
            status_code=500,
        )

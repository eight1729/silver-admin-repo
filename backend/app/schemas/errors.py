
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    error: str


class ErrorResponse(BaseModel):
    detail: ErrorDetail


def err(description: str) -> dict:
    return {"model": ErrorResponse, "description": description}

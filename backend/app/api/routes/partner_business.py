"""Admin/External-Business-owned Partner API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.partner_deps import get_authorized_partner_service, get_partner_conn
from app.schemas.errors import err
from app.schemas.recommended_jobs import RecommendedJobsResponse
from app.services.recommended_jobs_service import get_recommended_jobs_for_member

router = APIRouter(
    prefix="/partner", tags=["partner-business"],
    responses={401: err("api_key_required"), 403: err("invalid_api_key"),
               404: err("service_not_found"), 503: err("database_unavailable")},
)


@router.get(
    "/services/{service_id}/members/{member_code}/recommended-jobs",
    response_model=RecommendedJobsResponse,
    summary="Read a member's recommended jobs",
    responses={404: err("member_not_found / service_not_found")},
)
async def get_recommended_jobs(
    member_code: str,
    service: dict = Depends(get_authorized_partner_service),
    conn: AsyncConnection = Depends(get_partner_conn),
) -> RecommendedJobsResponse:
    result = await get_recommended_jobs_for_member(conn, service["service_id"], member_code)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "member_not_found", "member_code": member_code},
        )
    return result

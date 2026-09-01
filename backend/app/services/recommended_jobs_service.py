from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import repositories
from app.schemas.recommended_jobs import (
    RecommendedJob,
    RecommendedJobsResponse,
    RecommendedMember,
)


async def get_recommended_jobs_for_member(
    conn: AsyncConnection, service_id: str, member_code: str
) -> RecommendedJobsResponse | None:
    member_row = await repositories.get_member(conn, service_id, member_code)
    if member_row is None:
        return None

    job_rows = await repositories.get_recommended_job_rows(
        conn, service_id, member_code
    )

    member = RecommendedMember(**member_row)
    jobs = [RecommendedJob(**row) for row in job_rows]
    return RecommendedJobsResponse(member=member, jobs=jobs)

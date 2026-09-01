from datetime import datetime
from pydantic import BaseModel


class RecommendedMember(BaseModel):
    member_code: str
    display_name: str


class RecommendedJob(BaseModel):
    job_code: str
    title: str
    summary: str | None = None
    location_text: str | None = None
    work_date_text: str | None = None
    published_at: datetime | None = None


class RecommendedJobsResponse(BaseModel):
    member: RecommendedMember
    jobs: list[RecommendedJob]

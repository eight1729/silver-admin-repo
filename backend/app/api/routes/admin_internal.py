"""Versioned Admin business API. No request, response or exception payload logging."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.api.admin_internal_deps import get_admin_internal_service
from app.application.admin_internal_service import AdminInternalService
from app.domain.enums.enums import MemberVerificationStatus
from app.domain.errors.errors import (
    ExternalBusinessError, ExternalJobNotFoundError, ExternalMemberNotFoundError,
)
from app.domain.models.external_business import (
    ExternalJobDetail, ExternalJobSummary, ExternalMemberSummary, MemberVerificationInput,
)
from app.domain.ports.organization_service_scope import OrganizationServiceScopeNotConfiguredError
from app.schemas.admin_internal import (
    InternalErrorResponse, JobDetailRequest, MemberRequest, MemberVerificationRequest,
    MemberVerificationResponse, MultipleMemberMatch, NoMemberMatch, UniqueMemberMatch,
)


class InternalRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                return await handler(request)
            except HTTPException as exc:
                # Only fixed auth errors originate as HTTPException in this boundary.
                if exc.status_code in (401, 503) and exc.detail in (
                    {"error": "authentication_failed"}, {"error": "authentication_unavailable"},
                ):
                    return JSONResponse({"detail": exc.detail}, exc.status_code, headers=exc.headers)
                code, error = 500, "internal_error"
            except RequestValidationError:
                code, error = 422, "invalid_request"
            except OrganizationServiceScopeNotConfiguredError:
                code, error = 403, "scope_forbidden"
            except (ExternalMemberNotFoundError, ExternalJobNotFoundError):
                code, error = 404, "resource_not_found"
            except (ExternalBusinessError, TimeoutError, ResponseValidationError):
                code, error = 503, "external_system_unavailable"
            except Exception:
                code, error = 500, "internal_error"
            return JSONResponse({"detail": {"error": error}}, status_code=code)

        return safe_handler


router = APIRouter(
    prefix="/internal/v1", tags=["admin-internal"], route_class=InternalRoute,
    responses={
        code: {"model": InternalErrorResponse, "description": description}
        for code, description in {
            401: "Authentication failed", 403: "Scope forbidden", 404: "Resource not found",
            422: "Invalid request (input values are never echoed)",
            503: "Authentication configuration or business dependency unavailable",
            500: "Unexpected server failure",
        }.items()
    },
)


@router.post("/members:verify", response_model=MemberVerificationResponse)
async def verify_member(
    body: MemberVerificationRequest, service: AdminInternalService = Depends(get_admin_internal_service),
):
    result = await service.verify_member(
        body.service_id, MemberVerificationInput(body.member_number, body.name),
    )
    if result.status is MemberVerificationStatus.NO_MATCH:
        return NoMemberMatch()
    if result.status is MemberVerificationStatus.MULTIPLE_MATCH:
        return MultipleMemberMatch()
    if result.status is MemberVerificationStatus.UNIQUE_MATCH:
        return UniqueMemberMatch(external_member_id=result.external_member_id)
    raise ExternalBusinessError("invalid verification response")


@router.post("/members:summary", response_model=ExternalMemberSummary)
async def member_summary(
    body: MemberRequest, service: AdminInternalService = Depends(get_admin_internal_service),
):
    return await service.get_member_summary(body.service_id, body.external_member_id)


@router.post("/members:recommended-jobs", response_model=list[ExternalJobSummary])
async def recommended_jobs(
    body: MemberRequest, service: AdminInternalService = Depends(get_admin_internal_service),
):
    return await service.list_recommended_jobs(body.service_id, body.external_member_id)


@router.post("/jobs:detail", response_model=ExternalJobDetail)
async def job_detail(
    body: JobDetailRequest, service: AdminInternalService = Depends(get_admin_internal_service),
):
    return await service.get_job_detail(body.service_id, body.external_job_id)

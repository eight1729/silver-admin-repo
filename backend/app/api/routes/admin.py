from collections import Counter
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.admin_entry_deps import (
    get_admin_application_service,
    get_admin_line_send_mode as get_admin_line_send_mode_provider,
    get_admin_line_send_mode_for_runtime,
)
from app.api.admin_auth import (
    require_admin_operator,
    require_admin_role,
    require_admin_viewer,
)
from app.application.admin_service import (
    AdminApplicationService,
    AdminDependencyUnavailableError,
    AdminExternalSystemUnavailableError,
    AdminResourceNotFoundError,
    normalize_admin_exception,
)
from app.application.notification_service import (
    DuplicateTargetError,
    EmptyNotificationMessageError,
    InvalidNotificationCommandError,
    InvalidNotificationTypeError,
    OperationNotEditableError,
    OperationNotSendableError,
)
from app.domain.enums.enums import DeliveryStatus, OperationStatus
from app.domain.errors.errors import (
    ExternalJobNotFoundError,
    ExternalSystemUnavailableError,
    QueueError,
)
from app.domain.models.staff import AuthenticatedStaff
from app.schemas.admin import (
    AdminCandidateResponse,
    AdminDeliveriesResponse,
    AdminDeliveryResponse,
    AdminDeliverySummary,
    AdminJobDetailResponse,
    AdminJobSummaryResponse,
    AdminLineSendModeResponse,
    AdminMessageResponse,
    AdminNotificationLinkResponse,
    AdminOperationCreateRequest,
    AdminOperationResponse,
    AdminOperationUpdateRequest,
    AdminResetResponse,
    AdminTargetsUpdateRequest,
    AdminValidationResponse,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def _request_id() -> str:
    return f"admin-{uuid4()}"


@router.get("/line-send-mode", response_model=AdminLineSendModeResponse)
async def get_line_send_mode(
    request: Request,
    staff: AuthenticatedStaff = Depends(require_admin_viewer),
    fallback_mode: dict = Depends(get_admin_line_send_mode_provider),
):
    runtime_settings = getattr(request.app.state, "admin_runtime_settings", None)
    if runtime_settings is None or not runtime_settings.admin_local_integration_mode:
        return fallback_mode
    return await get_admin_line_send_mode_for_runtime(
        runtime_settings, integration=getattr(
            request.app.state, "admin_local_integration", None
        ), service_id=staff.service_id,
    )


def _translate(exc: Exception) -> None:
    exc = normalize_admin_exception(exc)
    if isinstance(exc, AdminExternalSystemUnavailableError):
        raise HTTPException(
            status_code=503, detail={"error": "external_system_unavailable"}
        )
    if isinstance(exc, (ExternalJobNotFoundError, AdminResourceNotFoundError)):
        raise HTTPException(status_code=404, detail={"error": "resource_not_found"})
    if isinstance(exc, (OperationNotEditableError, OperationNotSendableError)):
        raise HTTPException(status_code=409, detail={"error": "operation_conflict"})
    if isinstance(
        exc,
        (
            InvalidNotificationCommandError,
            EmptyNotificationMessageError,
            InvalidNotificationTypeError,
            DuplicateTargetError,
            ValueError,
        ),
    ):
        raise HTTPException(status_code=422, detail={"error": "invalid_request"})
    if isinstance(
        exc,
        (ExternalSystemUnavailableError, QueueError, AdminDependencyUnavailableError),
    ):
        raise HTTPException(status_code=503, detail={"error": "service_unavailable"})
    raise exc


def _operation(result) -> AdminOperationResponse:
    operation = result.operation
    return AdminOperationResponse(
        operation_id=operation.operation_id,
        job_id=operation.job_id,
        job_version=operation.job_version,
        notification_type=operation.notification_type,
        message=AdminMessageResponse(
            greeting=operation.message.greeting,
            introduction=operation.message.introduction,
            note=operation.message.note,
        ),
        status=operation.status,
        target_count=len(result.targets),
        selected_count=sum(item.selected for item in result.targets),
        validated_at=operation.validated_at,
        send_requested_at=operation.send_requested_at,
        completed_at=operation.completed_at,
        created_at=operation.created_at,
        updated_at=operation.updated_at,
    )


@router.get("/jobs", response_model=tuple[AdminJobSummaryResponse, ...])
async def list_jobs(
    staff: AuthenticatedStaff = Depends(require_admin_viewer),
    service: AdminApplicationService = Depends(get_admin_application_service),
):
    try:
        jobs = await service.list_jobs(staff.service_id)
        return tuple(
            AdminJobSummaryResponse(
                job_id=item.external_job_id,
                title=item.title,
                location=item.work_location_summary,
                status=item.status,
                version=item.version,
                summary=item.summary,
                work_days=item.work_days,
                work_time=item.work_time,
            )
            for item in jobs
        )
    except Exception as exc:
        _translate(exc)


@router.get("/jobs/{job_id}", response_model=AdminJobDetailResponse)
async def get_job(
    job_id: str,
    staff: AuthenticatedStaff = Depends(require_admin_viewer),
    service: AdminApplicationService = Depends(get_admin_application_service),
):
    try:
        item = await service.get_job(staff.service_id, job_id)
        return AdminJobDetailResponse(
            job_id=item.external_job_id,
            title=item.title,
            description=item.description,
            location=item.work_location,
            conditions=item.required_conditions,
            status=item.status,
            version=item.version,
            job_url=item.job_url or "",
            contact=item.staff_notes,
        )
    except Exception as exc:
        _translate(exc)


@router.get(
    "/jobs/{job_id}/notification-link",
    response_model=AdminNotificationLinkResponse,
)
async def get_notification_link(
    job_id: str,
    staff: AuthenticatedStaff = Depends(require_admin_viewer),
    service: AdminApplicationService = Depends(get_admin_application_service),
):
    try:
        await service.get_job(staff.service_id, job_id)
        return AdminNotificationLinkResponse(
            url=await service.resolve_notification_link(staff.service_id, job_id)
        )
    except HTTPException:
        raise
    except Exception as exc:
        _translate(exc)


@router.get(
    "/jobs/{job_id}/candidates", response_model=tuple[AdminCandidateResponse, ...]
)
async def list_candidates(
    job_id: str,
    staff: AuthenticatedStaff = Depends(require_admin_viewer),
    service: AdminApplicationService = Depends(get_admin_application_service),
):
    try:
        return tuple(
            AdminCandidateResponse(
                member_id=item.member_id,
                display_name=item.display_name,
                line_linked=item.line_linked,
                eligible=item.eligible,
                reason=item.reason,
                selected=item.selected,
                preference_summary=item.preference_summary,
            )
            for item in await service.list_candidates(staff.service_id, job_id)
        )
    except Exception as exc:
        _translate(exc)


@router.post(
    "/notification-operations",
    response_model=AdminOperationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_operation(
    body: AdminOperationCreateRequest,
    staff: AuthenticatedStaff = Depends(require_admin_operator),
    service: AdminApplicationService = Depends(get_admin_application_service),
):
    try:
        operation = await service.create_operation(
            service_id=staff.service_id,
            staff_id=staff.staff_id,
            job_id=body.job_id,
            notification_type=body.notification_type,
            greeting=body.greeting,
            introduction=body.introduction,
            note=body.note,
        )
        return _operation(
            await service.get_operation(staff.service_id, operation.operation_id)
        )
    except Exception as exc:
        _translate(exc)


@router.get(
    "/notification-operations/{operation_id}", response_model=AdminOperationResponse
)
async def get_operation(
    operation_id: UUID,
    staff: AuthenticatedStaff = Depends(require_admin_viewer),
    service: AdminApplicationService = Depends(get_admin_application_service),
):
    try:
        return _operation(await service.get_operation(staff.service_id, operation_id))
    except Exception as exc:
        _translate(exc)


@router.put(
    "/notification-operations/{operation_id}", response_model=AdminOperationResponse
)
async def update_operation(
    operation_id: UUID,
    body: AdminOperationUpdateRequest,
    staff: AuthenticatedStaff = Depends(require_admin_operator),
    service: AdminApplicationService = Depends(get_admin_application_service),
):
    try:
        await service.update_operation(
            service_id=staff.service_id,
            operation_id=operation_id,
            staff_id=staff.staff_id,
            greeting=body.greeting,
            introduction=body.introduction,
            note=body.note,
        )
        return _operation(await service.get_operation(staff.service_id, operation_id))
    except Exception as exc:
        _translate(exc)


@router.put(
    "/notification-operations/{operation_id}/targets",
    response_model=AdminOperationResponse,
)
async def replace_targets(
    operation_id: UUID,
    body: AdminTargetsUpdateRequest,
    staff: AuthenticatedStaff = Depends(require_admin_operator),
    service: AdminApplicationService = Depends(get_admin_application_service),
):
    try:
        return _operation(
            await service.replace_targets(
                service_id=staff.service_id,
                operation_id=operation_id,
                selected_member_ids=body.selected_member_ids,
                staff_id=staff.staff_id,
            )
        )
    except Exception as exc:
        _translate(exc)


@router.post(
    "/notification-operations/{operation_id}/validate",
    response_model=AdminValidationResponse,
)
async def validate_operation(
    operation_id: UUID,
    staff: AuthenticatedStaff = Depends(require_admin_operator),
    service: AdminApplicationService = Depends(get_admin_application_service),
):
    try:
        summary = await service.validate(
            service_id=staff.service_id,
            operation_id=operation_id,
            staff_id=staff.staff_id,
            request_id=_request_id(),
        )
        operation = (await service.get_operation(staff.service_id, operation_id)).operation
        reasons = tuple(
            sorted({item.reason for item in summary.target_results if item.reason})
        )
        if summary.blocking_reason:
            reasons = tuple(sorted(set(reasons) | {summary.blocking_reason}))
        return AdminValidationResponse(
            operation_id=operation_id,
            status=operation.status,
            can_proceed=summary.can_proceed,
            selected_count=summary.selected_target_count,
            sendable_count=summary.eligible_count,
            skipped_count=summary.skipped_count,
            reasons=reasons,
            version_changed=not summary.version_matches,
            external_system_blocked=operation.status
            is OperationStatus.BLOCKED_EXTERNAL_SYSTEM,
        )
    except Exception as exc:
        _translate(exc)


@router.post(
    "/notification-operations/{operation_id}/send",
    response_model=AdminOperationResponse,
)
async def send_operation(
    operation_id: UUID,
    staff: AuthenticatedStaff = Depends(require_admin_operator),
    service: AdminApplicationService = Depends(get_admin_application_service),
):
    try:
        await service.send(
            service_id=staff.service_id,
            operation_id=operation_id,
            staff_id=staff.staff_id,
            request_id=_request_id(),
        )
        return _operation(await service.get_operation(staff.service_id, operation_id))
    except Exception as exc:
        _translate(exc)


@router.get(
    "/notification-operations/{operation_id}/deliveries",
    response_model=AdminDeliveriesResponse,
)
async def list_deliveries(
    operation_id: UUID,
    staff: AuthenticatedStaff = Depends(require_admin_viewer),
    service: AdminApplicationService = Depends(get_admin_application_service),
):
    try:
        rows = await service.list_deliveries(staff.service_id, operation_id)
        counts = Counter(item.status for item in rows)
        return AdminDeliveriesResponse(
            items=tuple(
                AdminDeliveryResponse(
                    delivery_id=item.delivery_id,
                    member_id=item.member_id,
                    status=item.status,
                    reason_code=item.error_code,
                    created_at=item.created_at,
                    sent_at=item.sent_at,
                    updated_at=item.updated_at,
                )
                for item in rows
            ),
            summary=AdminDeliverySummary(
                **{state.value: counts[state] for state in DeliveryStatus}
            ),
        )
    except Exception as exc:
        _translate(exc)


@router.post("/demo/reset", response_model=AdminResetResponse)
async def reset_demo(
    staff: AuthenticatedStaff = Depends(require_admin_role),
    service: AdminApplicationService = Depends(get_admin_application_service),
):
    try:
        return AdminResetResponse(reset=(await service.reset(staff.service_id)).reset)
    except Exception as exc:
        _translate(exc)

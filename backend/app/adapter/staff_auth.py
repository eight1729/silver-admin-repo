from app.domain.enums.enums import StaffRole
from app.domain.errors.errors import DemoModeDisabledError, InactiveStaffError
from app.domain.models.staff import AuthenticatedStaff


class DemoStaffAuthenticator:
    """Local-demo authenticator with no credentials or external communication."""

    def __init__(
        self,
        *,
        staff_id: str = "demo-admin",
        display_name: str = "デモ管理者",
        role: StaffRole = StaffRole.ADMIN,
        service_id: str = "demo-service",
        active: bool = True,
        demo_mode_enabled: bool = True,
    ) -> None:
        self._staff = AuthenticatedStaff(
            staff_id=staff_id,
            display_name=display_name,
            role=role,
            service_id=service_id,
            active=active,
        )
        self._demo_mode_enabled = demo_mode_enabled

    async def get_current_staff(self) -> AuthenticatedStaff:
        if not self._demo_mode_enabled:
            raise DemoModeDisabledError("demo staff authentication is disabled")
        if not self._staff.active:
            raise InactiveStaffError("staff is inactive")
        return AuthenticatedStaff(
            staff_id=self._staff.staff_id,
            display_name=self._staff.display_name,
            role=self._staff.role,
            service_id=self._staff.service_id,
            active=self._staff.active,
        )

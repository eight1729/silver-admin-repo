from dataclasses import dataclass
from uuid import UUID

from app.domain.enums.enums import StaffRole
from app.domain.errors.errors import InvalidStaffConfigurationError


@dataclass(frozen=True, slots=True)
class StaffIdentity:
    staff_id: UUID
    identity_provider: str
    external_subject: str
    email: str | None
    display_name: str | None
    active: bool


@dataclass(frozen=True, slots=True)
class StaffServicePermission:
    staff_id: UUID
    service_id: str
    role: StaffRole


@dataclass(frozen=True, slots=True)
class AuthenticatedStaff:
    """Minimal authenticated staff context consumed by Admin use cases."""

    staff_id: str
    display_name: str
    role: StaffRole
    service_id: str
    active: bool

    def __post_init__(self) -> None:
        for field_name in ("staff_id", "display_name", "service_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise InvalidStaffConfigurationError(f"{field_name} is required")
            object.__setattr__(self, field_name, value.strip())
        if not isinstance(self.role, StaffRole):
            raise InvalidStaffConfigurationError("role is invalid")
        if not isinstance(self.active, bool):
            raise InvalidStaffConfigurationError("active must be boolean")

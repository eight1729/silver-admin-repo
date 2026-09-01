from typing import Protocol

from app.domain.models.staff import AuthenticatedStaff, StaffIdentity, StaffServicePermission


class StaffAuthenticator(Protocol):
    """Resolve the current authenticated staff without exposing credentials."""

    async def get_current_staff(self) -> AuthenticatedStaff: ...


class StaffIdentityRepository(Protocol):
    async def find_by_oidc_identity(
        self, issuer: str, subject: str
    ) -> tuple[StaffIdentity, tuple[StaffServicePermission, ...]] | None: ...
